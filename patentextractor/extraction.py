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

"""OpenChemIE extraction wrapper, result models, and RDKit enrichment."""

from __future__ import annotations

import importlib
import io
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from rdkit import Chem
from rdkit.Chem import Descriptors, rdMolDescriptors

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
    "prioritize_molecules",
    "reactions_from_pdf_results",
    "resolve_torch_device",
    "slice_pdf_pages",
    "_unpack_label",
]


class ExtractorUnavailableError(RuntimeError):
    """OpenChemIE (or a required backend) is not installed."""


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


@dataclass
class ExtractOptions:
    figures: bool = True
    text: bool = True
    corefs: bool = False
    reactions: bool = False
    merge_by_inchi: bool = True
    first_page: int = 1
    num_pages: int | None = None
    max_molecules: int | None = None
    batch_size: int = 16
    device: str = "cpu"
    crop_margin: float = 0.18


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


@dataclass
class ExtractedMolecule:
    smiles: str
    molfile: str = ""
    source: str = "figure"
    page: int | None = None
    score: float | None = None
    identifier: str = ""
    formula: str = ""
    molecular_weight: float | None = None
    inchi_key: str = ""
    crop_png: bytes | None = None
    context: str = ""
    bbox: tuple[float, ...] | None = None
    sources: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.sources:
            self.sources = [self.source]


@dataclass
class ExtractedReaction:
    page: int | None
    reactants: list[str]
    products: list[str]
    conditions: str
    source: str = "figure"


@dataclass
class ExtractionResult:
    pdf_path: str
    molecules: list[ExtractedMolecule]
    reactions: list[ExtractedReaction]
    warnings: list[str] = field(default_factory=list)


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
            importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name in (None, module_name):
                missing.append(module_name)
        except ImportError:
            # This is usually a dependency-version mismatch inside an installed package,
            # not a missing module. Those are diagnosed separately below.
            continue
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

    selected_device = resolve_torch_device(device)
    if device == "cuda" and selected_device == "cpu":
        logger.warning(
            "CUDA was requested for OpenChemIE, but no compatible NVIDIA GPU was detected; "
            "falling back to CPU."
        )
    torch_device = torch.device(selected_device)
    logger.info("Loading OpenChemIE on %s", torch_device)
    client = OpenChemIE(device=torch_device)
    configure_openchemie_client(client)
    return client


def parse_mol(*, smiles: str = "", molfile: str = "") -> Chem.Mol | None:
    """Parse a molecule from molfile first, then SMILES."""
    molfile = (molfile or "").strip()
    if molfile:
        mol = Chem.MolFromMolBlock(molfile, sanitize=False)
        if mol is not None:
            try:
                Chem.SanitizeMol(mol)
            except Exception:
                try:
                    mol.UpdatePropertyCache(strict=False)
                    Chem.GetSSSR(mol)
                except Exception:
                    logger.debug("Molfile sanitization failed", exc_info=True)
            return mol
    smiles = (smiles or "").strip()
    if not smiles:
        return None
    mol = Chem.MolFromSmiles(smiles)
    if mol is not None:
        return mol
    mol = Chem.MolFromSmiles(smiles, sanitize=False)
    if mol is None:
        return None
    try:
        mol.UpdatePropertyCache(strict=False)
        Chem.GetSSSR(mol)
    except Exception:
        logger.debug("SMILES sanitization failed", exc_info=True)
    return mol


def enrich_molecule(mol_rec: ExtractedMolecule) -> ExtractedMolecule:
    """Fill formula, MW, InChIKey, and canonical SMILES/molfile from RDKit."""
    mol = parse_mol(smiles=mol_rec.smiles, molfile=mol_rec.molfile)
    if mol is None:
        return mol_rec
    try:
        mol_rec.smiles = Chem.MolToSmiles(mol) or mol_rec.smiles
    except Exception:
        logger.debug("Canonical SMILES failed", exc_info=True)
    if not mol_rec.molfile:
        try:
            mol_rec.molfile = Chem.MolToMolBlock(mol) or ""
        except Exception:
            logger.debug("Molblock write failed", exc_info=True)
    try:
        mol_rec.formula = rdMolDescriptors.CalcMolFormula(mol)
    except Exception:
        logger.debug("Formula failed", exc_info=True)
    try:
        mol_rec.molecular_weight = round(float(Descriptors.MolWt(mol)), 3)
    except Exception:
        logger.debug("MolWt failed", exc_info=True)
    try:
        mol_rec.inchi_key = Chem.MolToInchiKey(mol) or ""
    except Exception:
        logger.debug("InChIKey failed", exc_info=True)
    return mol_rec


def ndarray_to_png_bytes(image: Any) -> bytes | None:
    """Encode a numpy/PIL crop to PNG bytes, or return None."""
    if image is None:
        return None
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        if hasattr(image, "save") and hasattr(image, "mode"):
            pil = image
            if pil.mode not in ("RGB", "L", "RGBA"):
                pil = pil.convert("RGB")
        else:
            import numpy as np

            arr = np.asarray(image)
            if arr.ndim == 2:
                pil = Image.fromarray(arr)
            else:
                pil = Image.fromarray(arr[..., :3])
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        logger.debug("Crop PNG encode failed", exc_info=True)
        return None


def _as_bbox(raw: Any) -> tuple[float, ...] | None:
    if raw is None:
        return None
    try:
        values = tuple(float(x) for x in raw)
    except (TypeError, ValueError):
        return None
    return values if len(values) >= 4 else None


def _expand_bbox_for_crop(
    bbox: tuple[float, ...] | None, margin_fraction: float = 0.18
) -> tuple[float, ...] | None:
    """Expand the original detected crop by a percentage in every direction.

    The requested context is taken from the source image and clipped only where
    the source image itself ends; no synthetic pixels are introduced.
    """
    if bbox is None or len(bbox) < 4:
        return None
    x0, y0, x1, y1 = [float(v) for v in bbox[:4]]
    if x1 <= x0 or y1 <= y0:
        return None
    width = x1 - x0
    height = y1 - y0
    pad_x = width * margin_fraction
    pad_y = height * margin_fraction
    return (x0 - pad_x, y0 - pad_y, x1 + pad_x, y1 + pad_y)


def _crop_image_from_bbox(image: Any, bbox: tuple[float, ...] | None) -> Any:
    """Extract a crop using actual source pixels, clipped to the source image bounds."""
    import math

    if image is None or bbox is None or len(bbox) < 4:
        return None
    try:
        import numpy as np
    except Exception:
        np = None

    try:
        if hasattr(image, "size") and hasattr(image, "crop"):
            try:
                from PIL import Image
            except ImportError:
                Image = None
            w, h = image.size
            x0, y0, x1, y1 = [float(v) for v in bbox[:4]]
            if all(-2.0 <= v <= 2.0 for v in (x0, y0, x1, y1)):
                left = math.floor(x0 * w)
                top = math.floor(y0 * h)
                right = math.ceil(x1 * w)
                bottom = math.ceil(y1 * h)
            else:
                left, top, right, bottom = (
                    math.floor(x0),
                    math.floor(y0),
                    math.ceil(x1),
                    math.ceil(y1),
                )
            left = max(0, min(w, left))
            top = max(0, min(h, top))
            right = max(0, min(w, right))
            bottom = max(0, min(h, bottom))
            if right <= left or bottom <= top:
                return None
            return image.crop((left, top, right, bottom))
        if np is not None:
            arr = np.asarray(image)
            if arr.ndim < 2:
                return None
            h, w = arr.shape[:2]
            x0, y0, x1, y1 = [float(v) for v in bbox[:4]]
            if all(-2.0 <= v <= 2.0 for v in (x0, y0, x1, y1)):
                left = int(np.floor(x0 * w))
                top = int(np.floor(y0 * h))
                right = int(np.ceil(x1 * w))
                bottom = int(np.ceil(y1 * h))
            else:
                left, top, right, bottom = int(np.floor(x0)), int(np.floor(y0)), int(np.ceil(x1)), int(np.ceil(y1))
            left = max(0, min(w, left))
            top = max(0, min(h, top))
            right = max(0, min(w, right))
            bottom = max(0, min(h, bottom))
            if right <= left or bottom <= top:
                return None
            return arr[top:bottom, left:right]
    except Exception:
        logger.debug("Figure crop extraction failed", exc_info=True)
    return None


def _join_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        parts = [_join_text(item) for item in value]
        return "; ".join(p for p in parts if p)
    return str(value).strip()


def molecules_from_figure_results(
    figures: list[dict], *, crop_margin: float = 0.18
) -> list[ExtractedMolecule]:
    """Flatten OpenChemIE figure-molecule output into records."""
    out: list[ExtractedMolecule] = []
    for figure in figures or []:
        if not isinstance(figure, dict):
            continue
        page = figure.get("page")
        full_figure_image = figure.get("image")
        for mol in figure.get("molecules") or []:
            if not isinstance(mol, dict):
                continue
            raw_bbox = _as_bbox(mol.get("bbox"))
            expanded_bbox = _expand_bbox_for_crop(raw_bbox, margin_fraction=max(0.0, float(crop_margin)))
            crop_image = mol.get("image")
            if crop_image is None and full_figure_image is not None and expanded_bbox is not None:
                crop_image = _crop_image_from_bbox(full_figure_image, expanded_bbox)
            if crop_image is None and raw_bbox is not None and full_figure_image is not None:
                crop_image = _crop_image_from_bbox(full_figure_image, raw_bbox)
            rec = ExtractedMolecule(
                smiles=str(mol.get("smiles") or ""),
                molfile=str(mol.get("molfile") or ""),
                source="figure",
                page=int(page) if page is not None else None,
                score=float(mol["score"]) if mol.get("score") is not None else None,
                bbox=expanded_bbox or raw_bbox,
                crop_png=ndarray_to_png_bytes(crop_image),
            )
            out.append(enrich_molecule(rec))
    return out


def molecules_from_text_results(pages: list[dict]) -> list[ExtractedMolecule]:
    """Turn named-entity spans into molecule records (SMILES when RDKit can parse)."""
    out: list[ExtractedMolecule] = []
    for page_block in pages or []:
        if not isinstance(page_block, dict):
            continue
        page = page_block.get("page")
        for paragraph in page_block.get("molecules") or []:
            if not isinstance(paragraph, dict):
                continue
            text = str(paragraph.get("text") or "")
            for label in paragraph.get("labels") or []:
                entity, start, end = _unpack_label(label, text)
                if not entity:
                    continue
                rec = ExtractedMolecule(
                    smiles=entity if parse_mol(smiles=entity) is not None else "",
                    source="text",
                    page=int(page) if page is not None else None,
                    identifier=entity,
                    context=text,
                )
                if rec.smiles:
                    enrich_molecule(rec)
                else:
                    rec.context = f"{entity}" + (f" — {text}" if text else "")
                out.append(rec)
    return out


def _unpack_label(label: Any, text: str) -> tuple[str, int, int]:
    """Accept (entity, start, end) or (type, start, end) and return the span text."""
    if not isinstance(label, (list, tuple)):
        return "", 0, 0
    try:
        raw = list(label)
        if len(raw) < 3:
            return "", 0, 0
        first, start, end = raw[0], int(raw[1]), int(raw[2])
    except (TypeError, ValueError):
        return "", 0, 0
    span = ""
    if 0 <= start < end <= len(text):
        span = text[start:end].strip()
    entity = span or str(first).strip()
    return entity, start, end


def reactions_from_pdf_results(
    payload: dict,
) -> tuple[list[ExtractedReaction], list[ExtractedMolecule]]:
    """Flatten OpenChemIE multimodal reaction output."""
    reactions: list[ExtractedReaction] = []
    molecules: list[ExtractedMolecule] = []
    for figure in (payload or {}).get("figures") or []:
        page = figure.get("page")
        for rxn in figure.get("reactions") or []:
            reactants = [
                str(item.get("smiles") or "")
                for item in rxn.get("reactants") or []
                if item.get("smiles")
            ]
            products = [
                str(item.get("smiles") or "")
                for item in rxn.get("products") or []
                if item.get("smiles")
            ]
            conditions = _join_text(
                [item.get("text") for item in rxn.get("conditions") or [] if item.get("text")]
            )
            reactions.append(
                ExtractedReaction(
                    page=int(page) if page is not None else None,
                    reactants=reactants,
                    products=products,
                    conditions=conditions,
                    source="figure",
                )
            )
            for role, items in (
                ("reaction_reactant", rxn.get("reactants") or []),
                ("reaction_product", rxn.get("products") or []),
            ):
                for item in items:
                    smiles = str(item.get("smiles") or "")
                    if not smiles:
                        continue
                    rec = ExtractedMolecule(
                        smiles=smiles,
                        molfile=str(item.get("molfile") or ""),
                        source=role,
                        page=int(page) if page is not None else None,
                        bbox=_as_bbox(item.get("bbox")),
                        context=conditions,
                    )
                    molecules.append(enrich_molecule(rec))
    for page_block in (payload or {}).get("text") or []:
        page = page_block.get("page")
        for sentence in page_block.get("reactions") or []:
            tokens = sentence.get("tokens") or []
            token_text = " ".join(str(t) for t in tokens)
            for rxn in sentence.get("reactions") or []:
                reactants = _role_smiles_from_text_rxn(rxn, "Reactants")
                products = _role_smiles_from_text_rxn(rxn, "Products")
                conditions = _join_text(rxn.get("Reaction") or rxn.get("conditions") or "")
                reactions.append(
                    ExtractedReaction(
                        page=int(page) if page is not None else None,
                        reactants=reactants,
                        products=products,
                        conditions=conditions or token_text,
                        source="text",
                    )
                )
    return reactions, molecules


def _role_smiles_from_text_rxn(rxn: dict, key: str) -> list[str]:
    value = rxn.get(key) or rxn.get(key.lower()) or []
    out: list[str] = []
    items = value if isinstance(value, list) else [value]
    for item in items:
        if isinstance(item, (list, tuple)) and item:
            token = item[0]
            if isinstance(token, (list, tuple)):
                text = " ".join(str(t) for t in token)
            else:
                text = str(token)
            if text:
                out.append(text)
        elif isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


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
            if rec.source not in existing.sources:
                existing.sources.append(rec.source)
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
            if existing.page is None:
                existing.page = rec.page
            continue
        index[key] = len(merged)
        merged.append(rec)
    return merged


def _molecule_is_valid(rec: ExtractedMolecule) -> bool:
    """True when a molecule record has a parseable structure to present to users."""
    if not rec.smiles and not rec.molfile:
        return False
    mol = parse_mol(smiles=rec.smiles, molfile=rec.molfile)
    return mol is not None


def molecule_quality_score(rec: ExtractedMolecule) -> float:
    """Return a derived quality score that separates valid, well-annotated hits from weak candidates."""
    raw = float(rec.score) if rec.score is not None else 0.0
    valid = 1.0 if _molecule_is_valid(rec) else 0.0
    quality = 0.5 * valid + 0.3 * max(0.0, min(1.0, raw))
    if rec.formula:
        quality += 0.08
    if rec.molecular_weight is not None:
        quality += 0.05
    if rec.molfile:
        quality += 0.05
    if rec.identifier:
        quality += 0.04
    if rec.source == "text":
        quality += 0.03
    return min(1.0, max(0.0, quality))


def prioritize_molecules(molecules: list[ExtractedMolecule]) -> list[ExtractedMolecule]:
    """Rank valid, better-annotated structures above malformed or low-quality candidates."""
    return sorted(
        molecules,
        key=lambda rec: (
            0 if _molecule_is_valid(rec) else 1,
            -molecule_quality_score(rec),
            rec.page if rec.page is not None else 1_000_000,
            str(rec.smiles or rec.molfile or rec.identifier or ""),
        ),
    )


class ExtractionCancelled(RuntimeError):
    """Raised when the GUI asks the worker to stop between extractor steps."""


def slice_pdf_pages(pdf_path: str, first_page: int, num_pages: int | None) -> tuple[str, int, bool]:
    """
    Restrict *pdf_path* to a page window.

    *first_page* is 1-based. Returns ``(path, page_offset, is_temporary)``.
    When the window is the whole file, the original path is returned.
    """
    first_page = max(1, int(first_page or 1))
    if first_page == 1:
        return pdf_path, 0, False
    try:
        from PyPDF2 import PdfReader, PdfWriter
    except ImportError as exc:
        raise ExtractorUnavailableError(
            "PyPDF2 is required to start extraction after page 1."
        ) from exc
    reader = PdfReader(pdf_path)
    total = len(reader.pages)
    start = min(first_page - 1, total)
    end = total if not num_pages else min(total, start + int(num_pages))
    if start >= total or start >= end:
        raise ValueError(f"Page range {first_page}… is outside this PDF ({total} pages).")
    writer = PdfWriter()
    for index in range(start, end):
        writer.add_page(reader.pages[index])
    handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    try:
        writer.write(handle)
    finally:
        handle.close()
    return handle.name, start, True


def _shift_pages(
    molecules: list[ExtractedMolecule], reactions: list[ExtractedReaction], offset: int
) -> None:
    if offset <= 0:
        return
    for rec in molecules:
        if rec.page is not None:
            rec.page += offset
    for rxn in reactions:
        if rxn.page is not None:
            rxn.page += offset


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
                pages = client.extract_molecules_from_text_in_pdf(work_pdf, **kwargs)
                molecules.extend(molecules_from_text_results(pages))
                molecules = _trim(molecules, warnings)
            except ExtractionCancelled:
                raise
            except Exception as exc:
                logger.exception("Text molecule extraction failed")
                warnings.append(f"Text extraction failed: {exc}")

        if options.corefs and not _at_cap(molecules):
            _check_cancel()
            _progress("Resolving molecule–label coreferences…")
            try:
                corefs = _normalize_openchemie_pages(
                    client.extract_molecule_corefs_from_figures_in_pdf(work_pdf, **kwargs)
                )
                _apply_coref_identifiers(molecules, corefs)
            except ExtractionCancelled:
                raise
            except Exception as exc:
                logger.exception("Coreference extraction failed")
                warnings.append(f"Coreference extraction failed: {exc}")

        if options.reactions and not _at_cap(molecules):
            _check_cancel()
            _progress("Extracting reactions…")
            try:
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


def _bbox_iou(a: tuple[float, ...] | None, b: tuple[float, ...] | None) -> float:
    if a is None or b is None or len(a) < 4 or len(b) < 4:
        return 0.0
    ax1, ay1, ax2, ay2 = a[:4]
    bx1, by1, bx2, by2 = b[:4]
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union else 0.0


def _apply_coref_identifiers(molecules: list[ExtractedMolecule], coref_figures: list[dict]) -> None:
    """Attach identifier text from coref pairs onto overlapping figure molecules."""
    page_mols: dict[int | None, list[ExtractedMolecule]] = {}
    for rec in molecules:
        if rec.source != "figure":
            continue
        page_mols.setdefault(rec.page, []).append(rec)

    for figure in coref_figures or []:
        page = figure.get("page")
        bboxes = figure.get("bboxes") or []
        candidates = page_mols.get(int(page) if page is not None else None, [])
        for pair in figure.get("corefs") or []:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            mol_i, id_i = int(pair[0]), int(pair[1])
            if mol_i >= len(bboxes) or id_i >= len(bboxes):
                continue
            mol_box = bboxes[mol_i]
            id_box = bboxes[id_i]
            label = _join_text(id_box.get("text") or id_box.get("category") or "")
            if not label or label.startswith("["):
                continue
            best: ExtractedMolecule | None = None
            best_iou = 0.15
            for rec in candidates:
                iou = _bbox_iou(rec.bbox, _as_bbox(mol_box.get("bbox")))
                if iou > best_iou:
                    best_iou = iou
                    best = rec
            if best is not None:
                if best.identifier and label not in best.identifier:
                    best.identifier = f"{best.identifier}; {label}"
                else:
                    best.identifier = label
