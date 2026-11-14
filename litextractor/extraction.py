# This file is part of LitExtractor.
# Copyright (C) 2026 Hunter Picard
#
# LitExtractor is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# LitExtractor is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with LitExtractor.  If not, see <https://www.gnu.org/licenses/>.

"""OpenChemIE extraction orchestration and molecule merging."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import Any, Callable, Protocol

from .cancellation import cancel_on_model_forward
from .chemistry import prioritize_molecules
from .crop_context import use_molecule_crop_margin
from .compat_checkpoint import openchemie_checkpoint_loads
from .extraction_coreference import apply_coref_identifiers
from .extraction_errors import ExtractionCancelled
from .extraction_pdf import shift_result_pages, slice_pdf_pages
from .extraction_results import (
    molecules_from_figure_results,
    parse_page_number,
    molecules_from_text_results,
    reactions_from_pdf_results,
)
from .extraction_runtime import load_openchemie
from .model_runtime import openchemie_client_session
from .models import ExtractOptions, ExtractedMolecule, ExtractedReaction, ExtractionResult

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], None]


class OpenChemIEClient(Protocol):
    """Subset of OpenChemIE used by this app (allows fakes in tests).

    OpenChemIE figure and figure-reaction page indexes are zero-based; the extraction pipeline
    converts them to one-based pages at the API boundary. Figures are detected once per run;
    the per-figure methods return one result per input image, in input order.
    """

    def extract_figures_from_pdf(self, pdf: str, **kwargs: Any) -> list[dict]:
        """Render ``pdf`` and detect its figures (``{"figure": {"image"}, "page"}`` dicts)."""
        ...

    def extract_molecules_from_figures(self, figures: list, **kwargs: Any) -> list[dict]:
        """Detect and read molecule structures in each figure image."""
        ...

    def extract_molecules_from_text_in_pdf(self, pdf: str, **kwargs: Any) -> list[dict]:
        """Find chemical names in the running text of ``pdf``."""
        ...

    def extract_molecule_corefs_from_figures(self, figures: list, **kwargs: Any) -> list[dict]:
        """Pair detected molecules with their text labels in each figure image."""
        ...

    def extract_reactions_from_pdf(self, pdf: str, **kwargs: Any) -> dict:
        """Extract reactions from the figures and text of ``pdf``."""
        ...


def merge_molecules_by_inchi(molecules: list[ExtractedMolecule]) -> list[ExtractedMolecule]:
    """Collapse records that share an InChIKey; keep records without one distinct.

    The first record of each group survives and absorbs the others' sources, pages,
    identifiers, context, crop image, and highest score.
    """
    merged: list[ExtractedMolecule] = []
    merged_index_by_key: dict[str, int] = {}
    for molecule in molecules:
        inchi_key = (molecule.inchi_key or "").strip()
        if not inchi_key:
            merged.append(molecule)
            continue
        if inchi_key not in merged_index_by_key:
            merged_index_by_key[inchi_key] = len(merged)
            merged.append(molecule)
            continue
        survivor = merged[merged_index_by_key[inchi_key]]
        for source in molecule.sources or [molecule.source]:
            if source not in survivor.sources:
                survivor.sources.append(source)
        if molecule.identifier and molecule.identifier not in survivor.identifier:
            survivor.identifier = (
                f"{survivor.identifier}; {molecule.identifier}"
                if survivor.identifier
                else molecule.identifier
            )
        if molecule.context and molecule.context not in survivor.context:
            survivor.context = (
                f"{survivor.context}\n{molecule.context}" if survivor.context else molecule.context
            )
        if survivor.crop_png is None and molecule.crop_png:
            survivor.crop_png = molecule.crop_png
        if survivor.score is None:
            survivor.score = molecule.score
        elif molecule.score is not None:
            survivor.score = max(survivor.score, molecule.score)
        for page in molecule.page_numbers:
            survivor.add_page(page)
    return merged


def _figure_images_and_pages(figures: Any) -> tuple[list[Any], list[int | None]]:
    """Return the images of detected figures and their one-based pages, skipping bad entries."""
    images: list[Any] = []
    pages: list[int | None] = []
    for figure in figures or []:
        figure_block = figure.get("figure") if isinstance(figure, dict) else None
        image = figure_block.get("image") if isinstance(figure_block, dict) else None
        if image is None:
            logger.warning("Ignoring detected figure without an image")
            continue
        page = parse_page_number(figure.get("page"))
        images.append(image)
        pages.append(None if page is None else page + 1)
    return images, pages


def _one_based_pages(figure_results: Any) -> Any:
    """Convert OpenChemIE's zero-based page indexes to one-based pages, in place."""
    for figure in figure_results or []:
        if not isinstance(figure, dict) or figure.get("page") is None:
            continue
        try:
            figure["page"] = int(figure["page"]) + 1
        except (TypeError, ValueError):
            logger.debug("Ignoring invalid OpenChemIE page value %r", figure.get("page"))
    return figure_results


@contextmanager
def _openchemie_model_call(should_cancel: Callable[[], bool] | None) -> Iterator[None]:
    """Scope for one OpenChemIE call: legacy checkpoint loading plus prompt cancellation."""
    with openchemie_checkpoint_loads(), cancel_on_model_forward(should_cancel):
        yield


class _ExtractionRun:
    """State and stages of one extraction of a single PDF."""

    def __init__(
        self,
        pdf_path: str,
        options: ExtractOptions,
        client: OpenChemIEClient | None,
        progress_callback: ProgressCallback | None,
        should_cancel: Callable[[], bool] | None,
    ) -> None:
        """Hold the inputs of one run; ``client=None`` means load the cached OpenChemIE."""
        self._pdf_path = pdf_path
        self._options = options
        self._client = client
        self._progress_callback = progress_callback
        self._should_cancel = should_cancel
        self._page_kwargs: dict[str, Any] = {}
        self._model_kwargs: dict[str, Any] = {"batch_size": options.batch_size}
        self._pdf_for_models = pdf_path
        self._figure_images: list[Any] = []
        self.molecules: list[ExtractedMolecule] = []
        self.reactions: list[ExtractedReaction] = []
        self.warnings: list[str] = []

    def execute(self) -> ExtractionResult:
        """Run every selected stage and return the merged, ranked, capped result."""
        options = self._options
        self._pdf_for_models, page_offset, is_temporary_pdf = slice_pdf_pages(
            self._pdf_path, options.first_page, options.num_pages
        )
        try:
            self._prepare_client(page_offset)
            if options.figures:
                self._run_figure_stage()
            if options.text and not self._molecule_cap_reached():
                self._run_text_stage()
            if options.corefs and any(
                molecule.figure_index is not None for molecule in self.molecules
            ):
                self._run_coreference_stage()
            if options.reactions:
                self._run_reaction_stage()

            self._raise_if_cancelled()
            shift_result_pages(self.molecules, self.reactions, page_offset)
            if options.merge_by_inchi:
                self.molecules = merge_molecules_by_inchi(self.molecules)
            self.molecules = prioritize_molecules(self.molecules)
            self._apply_molecule_cap()

            self._report_progress(
                f"Finished — {len(self.molecules)} molecule(s), {len(self.reactions)} reaction(s)."
            )
            return ExtractionResult(
                pdf_path=self._pdf_path,
                molecules=self.molecules,
                reactions=self.reactions,
                warnings=self.warnings,
            )
        finally:
            if is_temporary_pdf:
                try:
                    os.remove(self._pdf_for_models)
                except OSError:
                    logger.debug(
                        "Could not remove temp PDF %s", self._pdf_for_models, exc_info=True
                    )

    def _prepare_client(self, page_offset: int) -> None:
        """Load OpenChemIE if needed and build the keyword arguments shared by all stages."""
        if self._client is None:
            self._report_progress("Loading OpenChemIE models…")
            self._client = load_openchemie(self._options.device)
            self._raise_if_cancelled()
        if self._options.num_pages and page_offset == 0:
            self._page_kwargs["num_pages"] = self._options.num_pages
        self._model_kwargs.update(self._page_kwargs)
        text_reactions_supported = getattr(
            self._client, "_litextractor_text_reactions_supported", True
        )
        if self._options.reactions and text_reactions_supported is False:
            self.warnings.append(
                "Text-based reaction extraction is unavailable in this OpenChemIE setup; "
                "figure-based reactions will still be extracted."
            )

    def _run_figure_stage(self) -> None:
        """Detect figures once, then read the molecule structures in them.

        The detected figure images are kept so the coreference stage labels exactly the same
        figures instead of rendering the PDF and running layout detection a second time.
        """
        with self._stage("Detecting figures…", "Figure extraction"):
            with _openchemie_model_call(self._should_cancel):
                detected_figures = self._client.extract_figures_from_pdf(
                    self._pdf_for_models, output_bbox=True, **self._page_kwargs
                )
            self._figure_images, figure_pages = _figure_images_and_pages(detected_figures)
            if not self._figure_images:
                return
            self._report_progress(
                f"Reading structures in {len(self._figure_images)} figure(s)…"
            )
            with _openchemie_model_call(self._should_cancel):
                with use_molecule_crop_margin(self._options.crop_margin):
                    figure_results = self._client.extract_molecules_from_figures(
                        self._figure_images, batch_size=self._options.batch_size
                    )
            for result, page in zip(figure_results or [], figure_pages):
                if isinstance(result, dict):
                    result["page"] = page
            self.molecules.extend(
                molecules_from_figure_results(
                    figure_results, crop_margin=self._options.crop_margin
                )
            )
            self._apply_molecule_cap()

    def _run_text_stage(self) -> None:
        """Extract chemical names from the running text."""
        with self._stage("Extracting chemical names from text…", "Text extraction"):
            with _openchemie_model_call(self._should_cancel):
                text_pages = self._client.extract_molecules_from_text_in_pdf(
                    self._pdf_for_models, **self._model_kwargs
                )
            self.molecules.extend(molecules_from_text_results(text_pages))
            self._apply_molecule_cap()

    def _run_coreference_stage(self) -> None:
        """Attach figure labels (such as compound numbers) to the figure molecules.

        Runs on the figure images from the figure stage. MolScribe is skipped because the
        structures were already read with context-preserving crops; only labels are needed.
        """
        with self._stage("Resolving molecule–label coreferences…", "Coreference extraction"):
            with _openchemie_model_call(self._should_cancel):
                coreference_figures = self._client.extract_molecule_corefs_from_figures(
                    self._figure_images,
                    batch_size=self._options.batch_size,
                    molscribe=False,
                    ocr=True,
                )
            apply_coref_identifiers(self.molecules, coreference_figures)

    def _run_reaction_stage(self) -> None:
        """Extract reactions and the molecules that take part in them."""
        with self._stage("Extracting reactions…", "Reaction extraction"):
            with _openchemie_model_call(self._should_cancel):
                reaction_payload = self._client.extract_reactions_from_pdf(
                    self._pdf_for_models, **self._model_kwargs
                )
            if isinstance(reaction_payload, dict):
                _one_based_pages(reaction_payload.get("figures"))
            reactions, reaction_molecules = reactions_from_pdf_results(reaction_payload)
            self.reactions.extend(reactions)
            self.molecules.extend(reaction_molecules)
            self._apply_molecule_cap()

    @contextmanager
    def _stage(self, progress_message: str, stage_name: str) -> Iterator[None]:
        """Guard one stage: check cancellation, report progress, and turn failures into warnings.

        ``ExtractionCancelled`` derives from ``BaseException`` and therefore passes through.
        """
        self._raise_if_cancelled()
        self._report_progress(progress_message)
        try:
            yield
        except Exception as exc:
            logger.exception("%s failed", stage_name)
            self.warnings.append(f"{stage_name} failed: {exc}")

    def _report_progress(self, message: str) -> None:
        """Send ``message`` to the progress callback (if any) and the log."""
        if self._progress_callback is not None:
            self._progress_callback(message)
        logger.info(message)

    def _raise_if_cancelled(self) -> None:
        """Raise ``ExtractionCancelled`` when the caller has requested cancellation."""
        if self._should_cancel is not None and self._should_cancel():
            raise ExtractionCancelled("Extraction cancelled.")

    def _molecule_cap_reached(self) -> bool:
        """True when a molecule limit is set and the collected molecules meet it."""
        limit = self._options.max_molecules
        return bool(limit) and len(self.molecules) >= limit

    def _apply_molecule_cap(self) -> None:
        """Truncate to the molecule limit, recording a single partial-run warning."""
        limit = self._options.max_molecules
        if not limit or len(self.molecules) < limit:
            return
        if not any("partial run" in warning for warning in self.warnings):
            self.warnings.append(f"Stopped at {limit} structures (partial run).")
        self.molecules = self.molecules[:limit]


def extract_from_pdf(
    pdf_path: str,
    options: ExtractOptions,
    *,
    client: OpenChemIEClient | None = None,
    progress: ProgressCallback | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> ExtractionResult:
    """Run the selected OpenChemIE extractors and return enriched records.

    ``client`` defaults to the cached real OpenChemIE; pass a fake in tests. ``progress``
    receives human-readable status messages. ``should_cancel`` is polled between stages and
    during model inference; when it returns True, ``ExtractionCancelled`` is raised.
    """
    options.validate()
    # The cached client is shared and stateful, so only caller-supplied clients skip the lock.
    session = openchemie_client_session() if client is None else nullcontext()
    with session:
        return _ExtractionRun(pdf_path, options, client, progress, should_cancel).execute()
