# This file is part of PatentExtractor.
# Copyright (C) 2026 Hunter Picard
#
# PatentExtractor is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# PatentExtractor is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with PatentExtractor.  If not, see <https://www.gnu.org/licenses/>.

"""OpenChemIE extraction orchestration, PDF slicing, and coreference linking."""

from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
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
from .extraction_errors import ExtractorUnavailableError
from .extraction_pdf import slice_pdf_pages, shift_result_pages as _shift_pages
from .model_runtime import get_cached_openchemie_client, openchemie_client_session
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
    "cuda_available",
    "enrich_molecule",
    "extract_from_pdf",
    "merge_molecules_by_inchi",
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


def cuda_available() -> bool:
    """Return True only when torch has a working CUDA runtime and at least one GPU."""
    try:
        import torch
    except Exception:
        return False

    cuda_mod = getattr(torch, "cuda", None)
    if cuda_mod is None:
        return False
    try:
        return bool(cuda_mod.is_available() and cuda_mod.device_count() > 0)
    except Exception:
        return False


def resolve_torch_device(device: str = "cpu") -> str:
    """Return the runtime device string, falling back to CPU when CUDA is unavailable."""
    requested = (device or "cpu").lower()
    if requested == "cuda" and cuda_available():
        return "cuda"
    return "cpu"


def missing_openchemie_runtime_dependencies() -> list[str]:
    """Return only genuine missing top-level modules for the OpenChemIE runtime stack."""
    required = [
        "torch",
        "layoutparser",
        "easyocr",
        "IPython",
        "openchemie",
        "matplotlib",
        "seqeval",
    ]
    missing: list[str] = []
    for module_name in required:
        try:
            module_spec = importlib.util.find_spec(module_name)
        except (ImportError, ValueError):
            # This is usually a dependency-version mismatch inside an installed package,
            # not a missing module. Those are diagnosed separately below.
            continue
        if module_spec is None:
            missing.append(module_name)
    return missing


def build_openchemie_import_diagnostic(exc: ImportError, *, pdf_path: str | None = None) -> str:
    """Turn an OpenChemIE import failure into a precise compatibility diagnosis."""
    text = str(exc)
    lower = text.lower()
    sample_name = "ddr2.pdf" if pdf_path is None else Path(pdf_path).name

    if "cannot import name" in lower or "albumentations" in lower or "safe_rotate_enlarged_img_size" in lower:
        mismatch_hint = (
            "This is not a missing-module error: OpenChemIE is installed, but a dependency "
            "in the runtime stack is incompatible with the installed version set."
        )
        install_hint = "python -m pip install --no-deps -r requirements.txt"
        lines = [
            f"OpenChemIE could not be imported while processing '{sample_name}'.",
            f"Original import error: {exc}",
            "",
            mismatch_hint,
            "",
            "The usual cause is an outdated or incompatible albumentations/transformers stack. "
            "This project expects the pinned runtime in requirements.txt.",
            "",
            "Suggested next steps:",
            "  1. Reinstall the project runtime from the repo requirements in the active venv.",
            f"  2. Run: {install_hint}",
            "  3. Ensure you are using the project venv, not a system or Miniconda Python.",
            "  4. If the issue persists, upgrade/downgrade the stack to the pinned versions in requirements.txt.",
        ]
        return "\n".join(lines)

    if "pdftotext" in lower:
        lines = [
            f"OpenChemIE could not be imported while processing '{sample_name}'.",
            f"Original import error: {exc}",
            "",
            "This project uses a Windows-safe fallback for pdftotext when the native module is not available. "
            "The app should install the PyPDF2 shim automatically before importing OpenChemIE.",
            "",
            "Suggested next steps:",
            "  1. Make sure the app is launched from the project venv, not a system Python.",
            "  2. Reinstall the project runtime from requirements.txt in that venv.",
            "  3. Confirm the runtime stack is not mixed with a separate Miniconda or global install.",
            "  4. If this still fails, reinstall the project venv and re-run the pinned dependency setup.",
        ]
        return "\n".join(lines)

    missing: list[str] = []
    if isinstance(exc, ModuleNotFoundError) and exc.name:
        missing.append(exc.name)

    for module_name in (
        "layoutparser",
        "torch",
        "openchemie",
        "pytorch",
        "pypdf2",
        "pdftotext",
        "matplotlib",
        "seqeval",
        "easyocr",
        "IPython",
    ):
        if module_name in lower and module_name not in missing:
            missing.append(module_name)

    if not missing:
        missing = missing_openchemie_runtime_dependencies() or ["layoutparser", "torch", "openchemie"]

    install_hint = "python -m pip install " + " ".join(missing[:2])
    lines = [
        f"OpenChemIE could not be imported while processing '{sample_name}'.",
        f"Original import error: {exc}",
        "",
        "Likely missing dependency: " + ", ".join(missing),
        "",
        "This project requires a compatible OpenChemIE runtime, including layoutparser "
        "for the model stack and a Python-compatible torch build.",
        "",
        "Suggested next steps:",
        "  1. Ensure the app is using the project venv or a conda env with OpenChemIE installed.",
        f"  2. Install the missing dependency: {install_hint}",
        "  3. Confirm torch is compatible with your Python version, then install OpenChemIE with --no-deps.",
        "  4. Install Poppler for your OS if PDF rendering still fails.",
    ]
    return "\n".join(lines)


def load_openchemie(device: str = "cpu") -> Any:
    """Import and construct OpenChemIE, raising a clear error if it is missing."""
    selected_device = resolve_torch_device(device)
    if device == "cuda" and selected_device == "cpu":
        logger.warning(
            "CUDA was requested for OpenChemIE, but no compatible NVIDIA GPU was detected; "
            "falling back to CPU."
        )

    def create_client() -> Any:
        from .openchemie_compat import configure_openchemie_client, prepare_openchemie_imports

        missing = missing_openchemie_runtime_dependencies()
        if missing:
            detail = ModuleNotFoundError(f"No module named '{missing[0]}'")
            raise ExtractorUnavailableError(build_openchemie_import_diagnostic(detail)) from detail

        prepare_openchemie_imports()
        try:
            import torch
            from openchemie import OpenChemIE
        except ImportError as exc:
            raise ExtractorUnavailableError(build_openchemie_import_diagnostic(exc)) from exc

        torch_device = torch.device(selected_device)
        logger.info("Loading OpenChemIE on %s", torch_device)
        client = OpenChemIE(device=torch_device)
        configure_openchemie_client(client)
        return client

    return get_cached_openchemie_client(selected_device, create_client)


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


class ExtractionCancelled(RuntimeError):
    """Raised when the GUI asks the worker to stop between extractor steps."""


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
            client, "_patentextractor_text_reactions_supported", True
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

        if options.corefs:
            _check_cancel()
            _progress("Resolving molecule–label coreferences…")
            try:
                with openchemie_checkpoint_loads():
                    corefs = _normalize_openchemie_pages(
                        client.extract_molecule_corefs_from_figures_in_pdf(work_pdf, **kwargs)
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


