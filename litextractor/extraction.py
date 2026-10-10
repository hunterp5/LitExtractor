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

"""OpenChemIE extraction orchestration, PDF slicing, and coreference linking."""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Protocol

from .chemistry import (
    enrich_molecule,
    molecule_quality_score,
    parse_mol,
    prioritize_molecules,
)
from .crop_context import use_molecule_crop_margin
from .extraction_results import (
    _unpack_label,
    molecules_from_figure_results,
    molecules_from_text_results,
    reactions_from_pdf_results,
)
from .extraction_coreference import apply_coref_identifiers as _apply_coref_identifiers
from .extraction_errors import ExtractionCancelled, ExtractorUnavailableError
from .extraction_runtime import (
    build_openchemie_import_diagnostic as build_openchemie_import_diagnostic,
    cuda_available as cuda_available,
    load_openchemie as load_openchemie,
    missing_openchemie_runtime_dependencies as missing_openchemie_runtime_dependencies,
    resolve_torch_device as resolve_torch_device,
)
from .extraction_pdf import slice_pdf_pages, shift_result_pages as _shift_pages
from .model_runtime import openchemie_client_session
from .models import ExtractOptions, ExtractedMolecule, ExtractedReaction, ExtractionResult
from .openchemie_compat import openchemie_checkpoint_loads

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], None]

__all__ = [
    "ExtractOptions",
    "ExtractedMolecule",
    "ExtractedReaction",
    "ExtractionCancelled",
    "ExtractionResult",
    "ExtractorUnavailableError",
    "OpenChemIEClient",
    "apply_speed_preset",
    "build_openchemie_import_diagnostic",
    "cuda_available",
    "enrich_molecule",
    "extract_from_pdf",
    "load_openchemie",
    "merge_molecules_by_inchi",
    "missing_openchemie_runtime_dependencies",
    "molecule_quality_score",
    "molecules_from_figure_results",
    "molecules_from_text_results",
    "parse_mol",
    "prioritize_molecules",
    "reactions_from_pdf_results",
    "resolve_torch_device",
    "slice_pdf_pages",
    "_unpack_label",
]


class OpenChemIEClient(Protocol):
    """Subset of OpenChemIE used by this app (allows fakes in tests).

    OpenChemIE figure, coreference, and figure-reaction page indexes are zero-based;
    the extraction pipeline converts them to one-based pages at the API boundary.
    """

    def extract_molecules_from_figures_in_pdf(self, pdf: str, **kwargs: Any) -> list[dict]: ...

    def extract_molecules_from_text_in_pdf(self, pdf: str, **kwargs: Any) -> list[dict]: ...

    def extract_molecule_corefs_from_figures_in_pdf(
        self, pdf: str, **kwargs: Any
    ) -> list[dict]: ...

    def extract_reactions_from_pdf(self, pdf: str, **kwargs: Any) -> dict: ...


SPEED_PRESETS: dict[str, dict[str, Any]] = {
    "quick": {
        "figures": True,
        "text": False,
        "corefs": False,
        "reactions": False,
        "first_page": 1,
        "num_pages": 5,
        "max_molecules": 50,
    },
    "standard": {
        "figures": True,
        "text": False,
        "corefs": False,
        "reactions": False,
        "first_page": 1,
        "num_pages": 15,
        "max_molecules": 200,
    },
    "full": {
        "figures": True,
        "text": True,
        "corefs": False,
        "reactions": False,
        "first_page": 1,
        "num_pages": None,
        "max_molecules": None,
    },
}


def apply_speed_preset(name: str, base: ExtractOptions | None = None) -> ExtractOptions:
    """Return options for a named speed preset (quick / standard / full)."""
    opts = ExtractOptions() if base is None else ExtractOptions(**vars(base))
    spec = SPEED_PRESETS.get(name)
    if spec is None:
        return opts
    for key, value in spec.items():
        setattr(opts, key, value)
    return opts


def merge_molecules_by_inchi(molecules: list[ExtractedMolecule]) -> list[ExtractedMolecule]:
    """Collapse records that share an InChIKey; keep text-only rows distinct."""
    merged: list[ExtractedMolecule] = []
    index: dict[str, int] = {}
    for rec in molecules:
        key = (rec.inchi_key or "").strip()
        if not key:
            merged.append(rec)
            continue
        if key in index:
            existing = merged[index[key]]
            for source in rec.sources or [rec.source]:
                if source not in existing.sources:
                    existing.sources.append(source)
            if rec.identifier and rec.identifier not in existing.identifier:
                existing.identifier = (
                    f"{existing.identifier}; {rec.identifier}"
                    if existing.identifier
                    else rec.identifier
                )
            if rec.context and rec.context not in existing.context:
                existing.context = (
                    f"{existing.context}\n{rec.context}" if existing.context else rec.context
                )
            if existing.crop_png is None and rec.crop_png:
                existing.crop_png = rec.crop_png
            if existing.score is None:
                existing.score = rec.score
            elif rec.score is not None:
                existing.score = max(existing.score, rec.score)
            for page in rec.page_numbers:
                existing.add_page(page)
            continue
        index[key] = len(merged)
        merged.append(rec)
    return merged


def _normalize_openchemie_pages(figures: Any) -> Any:
    """Convert OpenChemIE's zero-based figure-page indexes to one-based pages."""
    for figure in figures or []:
        if not isinstance(figure, dict) or figure.get("page") is None:
            continue
        try:
            figure["page"] = int(figure["page"]) + 1
        except (TypeError, ValueError):
            logger.debug("Ignoring invalid OpenChemIE page value %r", figure.get("page"))
    return figures


def extract_from_pdf(
    pdf_path: str,
    options: ExtractOptions,
    *,
    client: OpenChemIEClient | None = None,
    progress: ProgressCallback | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> ExtractionResult:
    """Run the selected OpenChemIE extractors and return enriched records."""
    options.validate()
    if client is None:
        with openchemie_client_session():
            return _extract_from_pdf(
                pdf_path,
                options,
                client=client,
                progress=progress,
                should_cancel=should_cancel,
            )
    return _extract_from_pdf(
        pdf_path,
        options,
        client=client,
        progress=progress,
        should_cancel=should_cancel,
    )


def _extract_from_pdf(
    pdf_path: str,
    options: ExtractOptions,
    *,
    client: OpenChemIEClient | None = None,
    progress: ProgressCallback | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> ExtractionResult:
    """Implementation shared by cached-client and caller-supplied extraction runs."""

    def _progress(message: str) -> None:
        if progress is not None:
            progress(message)
        logger.info(message)

    def _check_cancel() -> None:
        if should_cancel is not None and should_cancel():
            raise ExtractionCancelled("Extraction cancelled.")

    def _at_cap(mols: list[ExtractedMolecule]) -> bool:
        cap = options.max_molecules
        return bool(cap) and len(mols) >= int(cap)

    def _trim(mols: list[ExtractedMolecule], warnings: list[str]) -> list[ExtractedMolecule]:
        cap = options.max_molecules
        if not cap or len(mols) < int(cap):
            return mols
        cap = int(cap)
        if not any("partial run" in item for item in warnings):
            warnings.append(f"Stopped at {cap} structures (partial run).")
        return mols[:cap]

    work_pdf, page_offset, is_temp = slice_pdf_pages(
        pdf_path, options.first_page, options.num_pages
    )
    try:
        if client is None:
            _progress("Loading OpenChemIE models…")
            client = load_openchemie(options.device)
            _check_cancel()
        assert client is not None

        kwargs: dict[str, Any] = {"batch_size": options.batch_size}
        if options.num_pages and page_offset == 0:
            kwargs["num_pages"] = options.num_pages

        molecules: list[ExtractedMolecule] = []
        reactions: list[ExtractedReaction] = []
        warnings: list[str] = []
        if options.reactions and getattr(
            client, "_litextractor_text_reactions_supported", True
        ) is False:
            warnings.append(
                "Text-based reaction extraction is unavailable in this OpenChemIE setup; "
                "figure-based reactions will still be extracted."
            )

        if options.figures:
            _check_cancel()
            _progress("Extracting molecules from figures…")
            try:
                with openchemie_checkpoint_loads():
                    with use_molecule_crop_margin(options.crop_margin):
                        figures = _normalize_openchemie_pages(
                            client.extract_molecules_from_figures_in_pdf(work_pdf, **kwargs)
                        )
                molecules.extend(molecules_from_figure_results(figures, crop_margin=options.crop_margin))
                molecules = _trim(molecules, warnings)
            except ExtractionCancelled:
                raise
            except Exception as exc:
                logger.exception("Figure molecule extraction failed")
                warnings.append(f"Figure extraction failed: {exc}")

        if options.text and not _at_cap(molecules):
            _check_cancel()
            _progress("Extracting chemical names from text…")
            try:
                with openchemie_checkpoint_loads():
                    pages = client.extract_molecules_from_text_in_pdf(work_pdf, **kwargs)
                molecules.extend(molecules_from_text_results(pages))
                molecules = _trim(molecules, warnings)
            except ExtractionCancelled:
                raise
            except Exception as exc:
                logger.exception("Text molecule extraction failed")
                warnings.append(f"Text extraction failed: {exc}")

        if options.corefs and any(molecule.source == "figure" for molecule in molecules):
            _check_cancel()
            _progress("Resolving molecule–label coreferences…")
            try:
                with openchemie_checkpoint_loads():
                    corefs = _normalize_openchemie_pages(
                        client.extract_molecule_corefs_from_figures_in_pdf(
                            work_pdf, **kwargs, molscribe=False, ocr=True
                        )
                    )
                _apply_coref_identifiers(molecules, corefs)
            except ExtractionCancelled:
                raise
            except Exception as exc:
                logger.exception("Coreference extraction failed")
                warnings.append(f"Coreference extraction failed: {exc}")

        if options.reactions:
            _check_cancel()
            _progress("Extracting reactions…")
            try:
                with openchemie_checkpoint_loads():
                    payload = client.extract_reactions_from_pdf(work_pdf, **kwargs)
                if isinstance(payload, dict):
                    _normalize_openchemie_pages(payload.get("figures"))
                rxns, rxn_mols = reactions_from_pdf_results(payload)
                reactions.extend(rxns)
                molecules.extend(rxn_mols)
                molecules = _trim(molecules, warnings)
            except ExtractionCancelled:
                raise
            except Exception as exc:
                logger.exception("Reaction extraction failed")
                warnings.append(f"Reaction extraction failed: {exc}")

        _check_cancel()
        _shift_pages(molecules, reactions, page_offset)
        if options.merge_by_inchi:
            molecules = merge_molecules_by_inchi(molecules)
        molecules = prioritize_molecules(molecules)
        molecules = _trim(molecules, warnings)

        _progress(f"Finished — {len(molecules)} molecule(s), {len(reactions)} reaction(s).")
        return ExtractionResult(
            pdf_path=pdf_path,
            molecules=molecules,
            reactions=reactions,
            warnings=warnings,
        )
    finally:
        if is_temp:
            try:
                os.remove(work_pdf)
            except OSError:
                logger.debug("Could not remove temp PDF %s", work_pdf, exc_info=True)


