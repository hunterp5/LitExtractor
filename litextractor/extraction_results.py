"""Normalize OpenChemIE figure, text, and reaction outputs into domain records."""

from __future__ import annotations

import io
import logging
import math
from typing import Any

from .chemistry import enrich_molecule, parse_mol
from .crop_context import DEFAULT_MOLECULE_CROP_MARGIN
from .models import ExtractedMolecule, ExtractedReaction

logger = logging.getLogger(__name__)


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
    bbox: tuple[float, ...] | None,
    margin_fraction: float = DEFAULT_MOLECULE_CROP_MARGIN,
) -> tuple[float, ...] | None:
    """Expand a normalized molecule box; clipping occurs later during source-image cropping."""
    if bbox is None or len(bbox) < 4:
        return None
    x0, y0, x1, y1 = [float(value) for value in bbox[:4]]
    if x1 <= x0 or y1 <= y0:
        return None
    width = x1 - x0
    height = y1 - y0
    pad_x = width * margin_fraction
    pad_y = height * margin_fraction
    return (x0 - pad_x, y0 - pad_y, x1 + pad_x, y1 + pad_y)


def _crop_image_from_bbox(image: Any, bbox: tuple[float, ...] | None) -> Any:
    """Extract a crop using actual source pixels, clipped to the source image bounds."""
    if image is None or bbox is None or len(bbox) < 4:
        return None
    try:
        is_pil = hasattr(image, "size") and hasattr(image, "crop")
        if is_pil:
            width, height = image.size
        else:
            import numpy as np

            array = np.asarray(image)
            if array.ndim < 2:
                return None
            height, width = array.shape[:2]
        x0, y0, x1, y1 = [float(value) for value in bbox[:4]]
        if all(-2.0 <= value <= 2.0 for value in (x0, y0, x1, y1)):
            x0, x1 = x0 * width, x1 * width
            y0, y1 = y0 * height, y1 * height
        left = max(0, min(width, math.floor(x0)))
        top = max(0, min(height, math.floor(y0)))
        right = max(0, min(width, math.ceil(x1)))
        bottom = max(0, min(height, math.ceil(y1)))
        if right <= left or bottom <= top:
            return None
        if is_pil:
            return image.crop((left, top, right, bottom))
        return array[top:bottom, left:right]
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
        return "; ".join(part for part in parts if part)
    return str(value).strip()


def _page_number(value: Any) -> int | None:
    """Normalize a vendor page value without allowing malformed metadata to abort parsing."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        logger.warning("Ignoring invalid OpenChemIE page value %r", value)
        return None


def _mapping_entries(value: Any, description: str) -> list[dict]:
    """Return mapping entries from a vendor list, logging and skipping malformed values."""
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        logger.warning("Ignoring malformed OpenChemIE %s: expected a list", description)
        return []
    entries: list[dict] = []
    for index, entry in enumerate(value):
        if isinstance(entry, dict):
            entries.append(entry)
        else:
            logger.warning(
                "Ignoring malformed OpenChemIE %s entry %d: expected a mapping",
                description,
                index,
            )
    return entries


def molecules_from_figure_results(
    figures: list[dict], *, crop_margin: float = DEFAULT_MOLECULE_CROP_MARGIN
) -> list[ExtractedMolecule]:
    """Flatten OpenChemIE figure-molecule output into records."""
    molecules: list[ExtractedMolecule] = []
    for figure in figures or []:
        if not isinstance(figure, dict):
            continue
        page = _page_number(figure.get("page"))
        full_figure_image = figure.get("image")
        for molecule in figure.get("molecules") or []:
            if not isinstance(molecule, dict):
                continue
            raw_bbox = _as_bbox(molecule.get("bbox"))
            expanded_bbox = _expand_bbox_for_crop(
                raw_bbox, margin_fraction=max(0.0, float(crop_margin))
            )
            crop_image = molecule.get("image")
            if crop_image is None and full_figure_image is not None and expanded_bbox is not None:
                crop_image = _crop_image_from_bbox(full_figure_image, expanded_bbox)
            if crop_image is None and raw_bbox is not None and full_figure_image is not None:
                crop_image = _crop_image_from_bbox(full_figure_image, raw_bbox)
            raw_score = molecule.get("score")
            try:
                score = float(raw_score) if raw_score is not None else None
            except (TypeError, ValueError, OverflowError):
                logger.warning("Ignoring invalid OpenChemIE molecule score %r", raw_score)
                score = None
            record = ExtractedMolecule(
                smiles=str(molecule.get("smiles") or ""),
                molfile=str(molecule.get("molfile") or ""),
                source="figure",
                page=page,
                score=score,
                bbox=expanded_bbox or raw_bbox,
                crop_png=ndarray_to_png_bytes(crop_image),
            )
            molecules.append(enrich_molecule(record))
    return molecules


def molecules_from_text_results(pages: list[dict]) -> list[ExtractedMolecule]:
    """Turn named-entity spans into molecule records (SMILES when RDKit can parse)."""
    molecules: list[ExtractedMolecule] = []
    for page_block in pages or []:
        if not isinstance(page_block, dict):
            continue
        page = _page_number(page_block.get("page"))
        for paragraph in page_block.get("molecules") or []:
            if not isinstance(paragraph, dict):
                continue
            text = str(paragraph.get("text") or "")
            for label in paragraph.get("labels") or []:
                entity, _start, _end = _unpack_label(label, text)
                if not entity:
                    continue
                record = ExtractedMolecule(
                    smiles=entity if parse_mol(smiles=entity) is not None else "",
                    source="text",
                    page=page,
                    identifier=entity,
                    context=text,
                )
                if record.smiles:
                    enrich_molecule(record)
                else:
                    record.context = f"{entity}" + (f" — {text}" if text else "")
                molecules.append(record)
    return molecules


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
    if not isinstance(payload, dict):
        logger.warning("Ignoring malformed OpenChemIE reaction payload: expected a mapping")
        return reactions, molecules

    for figure in _mapping_entries(payload.get("figures"), "reaction figures"):
        page = _page_number(figure.get("page"))
        for reaction in _mapping_entries(figure.get("reactions"), "figure reactions"):
            reactant_entries = _mapping_entries(reaction.get("reactants"), "reaction reactants")
            product_entries = _mapping_entries(reaction.get("products"), "reaction products")
            condition_entries = _mapping_entries(reaction.get("conditions"), "reaction conditions")
            reactants = [str(item["smiles"]) for item in reactant_entries if item.get("smiles")]
            products = [str(item["smiles"]) for item in product_entries if item.get("smiles")]
            conditions = _join_text(
                [item.get("text") for item in condition_entries if item.get("text")]
            )
            reactions.append(
                ExtractedReaction(
                    page=page,
                    reactants=reactants,
                    products=products,
                    conditions=conditions,
                    source="figure",
                )
            )
            for role, items in (
                ("reaction_reactant", reactant_entries),
                ("reaction_product", product_entries),
            ):
                for item in items:
                    smiles = str(item.get("smiles") or "")
                    if not smiles:
                        continue
                    record = ExtractedMolecule(
                        smiles=smiles,
                        molfile=str(item.get("molfile") or ""),
                        source=role,
                        page=page,
                        bbox=_as_bbox(item.get("bbox")),
                        context=conditions,
                    )
                    molecules.append(enrich_molecule(record))

    for page_block in _mapping_entries(payload.get("text"), "text reaction pages"):
        page = _page_number(page_block.get("page"))
        for sentence in _mapping_entries(page_block.get("reactions"), "reaction sentences"):
            tokens = sentence.get("tokens") or []
            token_text = " ".join(str(token) for token in tokens)
            for reaction in _mapping_entries(sentence.get("reactions"), "text reactions"):
                reactants = _role_smiles_from_text_rxn(reaction, "Reactants")
                products = _role_smiles_from_text_rxn(reaction, "Products")
                conditions = _join_text(
                    reaction.get("Reaction") or reaction.get("conditions") or ""
                )
                reactions.append(
                    ExtractedReaction(
                        page=page,
                        reactants=reactants,
                        products=products,
                        conditions=conditions or token_text,
                        source="text",
                    )
                )
    return reactions, molecules


def _role_smiles_from_text_rxn(reaction: dict, key: str) -> list[str]:
    value = reaction.get(key) or reaction.get(key.lower()) or []
    smiles_values: list[str] = []
    items = value if isinstance(value, list) else [value]
    for item in items:
        if isinstance(item, (list, tuple)) and item:
            token = item[0]
            text = " ".join(str(value) for value in token) if isinstance(token, (list, tuple)) else str(token)
            if text:
                smiles_values.append(text)
        elif isinstance(item, str) and item.strip():
            smiles_values.append(item.strip())
    return smiles_values
