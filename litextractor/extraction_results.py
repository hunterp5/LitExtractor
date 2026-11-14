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

"""Normalize OpenChemIE figure, text, and reaction outputs into domain records."""

from __future__ import annotations

import io
import logging
import math
from typing import Any

from .chemistry import enrich_molecule, parse_mol
from .models import ExtractedMolecule, ExtractedReaction

logger = logging.getLogger(__name__)


def image_to_png_bytes(image: Any) -> bytes | None:
    """Encode a PIL image or array-like crop as PNG bytes, or return None on failure."""
    if image is None:
        return None
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        if hasattr(image, "save") and hasattr(image, "mode"):
            pil_image = image
            if pil_image.mode not in ("RGB", "L", "RGBA"):
                pil_image = pil_image.convert("RGB")
        else:
            import numpy as np

            pixel_array = np.asarray(image)
            if pixel_array.ndim == 2:
                pil_image = Image.fromarray(pixel_array)
            else:
                pil_image = Image.fromarray(pixel_array[..., :3])
        png_buffer = io.BytesIO()
        pil_image.save(png_buffer, format="PNG")
        return png_buffer.getvalue()
    except Exception:
        logger.debug("Crop PNG encode failed", exc_info=True)
        return None


def parse_bbox(raw_bbox: Any) -> tuple[float, ...] | None:
    """Convert a vendor bounding box to a float tuple, or None if it has fewer than 4 values."""
    if raw_bbox is None:
        return None
    try:
        values = tuple(float(value) for value in raw_bbox)
    except (TypeError, ValueError):
        return None
    return values if len(values) >= 4 else None


def _crop_image_from_bbox(image: Any, bbox: tuple[float, ...] | None) -> Any:
    """Extract a crop using actual source pixels, clipped to the source image bounds.

    ``bbox`` is either normalized (all values within -2..2, scaled by the image size) or in
    pixels. Works for PIL images and NumPy-like arrays; returns None when the crop is empty.
    """
    if image is None or bbox is None or len(bbox) < 4:
        return None
    try:
        is_pil_image = hasattr(image, "size") and hasattr(image, "crop")
        if is_pil_image:
            image_width, image_height = image.size
        else:
            import numpy as np

            pixel_array = np.asarray(image)
            if pixel_array.ndim < 2:
                return None
            image_height, image_width = pixel_array.shape[:2]
        left, top, right, bottom = [float(value) for value in bbox[:4]]
        if all(-2.0 <= value <= 2.0 for value in (left, top, right, bottom)):
            left, right = left * image_width, right * image_width
            top, bottom = top * image_height, bottom * image_height
        left_pixel = max(0, min(image_width, math.floor(left)))
        top_pixel = max(0, min(image_height, math.floor(top)))
        right_pixel = max(0, min(image_width, math.ceil(right)))
        bottom_pixel = max(0, min(image_height, math.ceil(bottom)))
        if right_pixel <= left_pixel or bottom_pixel <= top_pixel:
            return None
        if is_pil_image:
            return image.crop((left_pixel, top_pixel, right_pixel, bottom_pixel))
        return pixel_array[top_pixel:bottom_pixel, left_pixel:right_pixel]
    except Exception:
        logger.debug("Figure crop extraction failed", exc_info=True)
    return None


def join_text(value: Any) -> str:
    """Flatten a string or nested list of strings into one "; "-separated string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        parts = [join_text(item) for item in value]
        return "; ".join(part for part in parts if part)
    return str(value).strip()


def parse_page_number(value: Any) -> int | None:
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


def _optional_float(raw_value: Any, description: str) -> float | None:
    """Return *raw_value* as a finite float, or None (logging why) if it is missing or bad."""
    if raw_value is None:
        return None
    try:
        value = float(raw_value)
    except (TypeError, ValueError, OverflowError):
        value = math.nan
    if not math.isfinite(value):
        logger.warning("Ignoring invalid OpenChemIE molecule %s %r", description, raw_value)
        return None
    return value


def molecules_from_figure_results(figures: list[dict]) -> list[ExtractedMolecule]:
    """Flatten OpenChemIE figure-molecule output into enriched molecule records.

    Each molecule gets a PNG crop: the detector's own crop when present, otherwise the full
    figure cropped to its bounding box. ``figure_index`` is the figure's position in
    ``figures``, and ``confidence`` is MolScribe's confidence when it was reported.
    """
    molecules: list[ExtractedMolecule] = []
    for figure_index, figure in enumerate(figures or []):
        if not isinstance(figure, dict):
            continue
        page = parse_page_number(figure.get("page"))
        full_figure_image = figure.get("image")
        for detected_molecule in figure.get("molecules") or []:
            if not isinstance(detected_molecule, dict):
                continue
            detected_bbox = parse_bbox(detected_molecule.get("bbox"))
            crop_image = detected_molecule.get("image")
            if crop_image is None and detected_bbox is not None and full_figure_image is not None:
                crop_image = _crop_image_from_bbox(full_figure_image, detected_bbox)
            molecule = ExtractedMolecule(
                smiles=str(detected_molecule.get("smiles") or ""),
                molfile=str(detected_molecule.get("molfile") or ""),
                source="figure",
                page=page,
                score=_optional_float(detected_molecule.get("score"), "score"),
                confidence=_optional_float(
                    detected_molecule.get("confidence"), "confidence"
                ),
                bbox=detected_bbox,
                figure_index=figure_index,
                crop_png=image_to_png_bytes(crop_image),
            )
            _drop_misread_fragments(molecule)
            molecules.append(enrich_molecule(molecule))
    return molecules


def _drop_misread_fragments(molecule: ExtractedMolecule) -> None:
    """Remove stray pieces read from text beside the structure, noting them in the context."""
    from .chemistry import remove_stray_fragments

    smiles, molfile, removed = remove_stray_fragments(molecule.smiles, molecule.molfile)
    if removed:
        molecule.smiles, molecule.molfile = smiles, molfile
        note = "Removed stray fragments read beside the structure: " + ", ".join(removed)
        molecule.context = f"{note}. {molecule.context}".strip() if molecule.context else note


#: Chemical-name categories that name one compound. Abbreviations ("ATP", "PPI"), families
#: ("saponins"), formulas and lists ("cucurbitacin B and D") are left out.
COMPOUND_NAME_TYPES = frozenset({"TRIVIAL", "SYSTEMATIC", "IDENTIFIER"})
_KNOWN_NAME_TYPES = COMPOUND_NAME_TYPES | {"ABBREVIATION", "FAMILY", "FORMULA", "MULTIPLE"}


def _names_a_compound(label: Any) -> bool:
    """False for labels of a category that does not name one compound."""
    kind = label[0] if isinstance(label, (list, tuple)) and label else None
    return not (isinstance(kind, str) and kind in _KNOWN_NAME_TYPES
                and kind not in COMPOUND_NAME_TYPES)


def split_name_span(entity: str) -> list[str]:
    """The compound names in one name span; [] when it names none.

    Text read from tables and figure labels runs cells together, so the name model returns
    spans such as "Avitinib Avitinib" or "Brigatinib Afatinib": several capitalized one-word
    names, split apart here and de-duplicated. Spans without letters ("4.6.6", a section
    number) and substituent names ("9-heterocyclyl") are dropped.
    """
    entity = " ".join(entity.split())
    if not any(char.isalpha() for char in entity) or entity.lower().endswith("yl"):
        return []
    words = entity.split()
    if len(words) > 1 and all(word[:1].isupper() and word.isalpha() and len(word) >= 5
                              for word in words):
        return list(dict.fromkeys(words))
    return [entity]


def molecules_from_text_results(pages: list[dict]) -> list[ExtractedMolecule]:
    """Turn named-entity spans into molecule records (SMILES when RDKit can parse)."""
    molecules: list[ExtractedMolecule] = []
    for page_block in pages or []:
        if not isinstance(page_block, dict):
            continue
        page = parse_page_number(page_block.get("page"))
        for paragraph in page_block.get("molecules") or []:
            if not isinstance(paragraph, dict):
                continue
            paragraph_text = str(paragraph.get("text") or "")
            for label in paragraph.get("labels") or []:
                if not _names_a_compound(label):
                    continue
                entity, _start, _end = unpack_label(label, paragraph_text)
                for name in split_name_span(entity):
                    molecules.append(_text_molecule(name, page, paragraph_text))
    return molecules


def _text_molecule(entity: str, page: int | None, paragraph_text: str) -> ExtractedMolecule:
    """A record for one name found in the text, with a structure when the name is SMILES."""
    molecule = ExtractedMolecule(
        smiles=entity if parse_mol(smiles=entity) is not None else "",
        source="text",
        page=page,
        identifier=entity,
        context=paragraph_text,
    )
    if molecule.smiles:
        enrich_molecule(molecule)
    else:
        molecule.context = entity + (f" — {paragraph_text}" if paragraph_text else "")
    return molecule


def unpack_label(label: Any, text: str) -> tuple[str, int, int]:
    """Read a label and return ``(span_text, start, end)``.

    Labels come as ``(entity_or_type, start, end)`` (as documented) or, from the chemical-name
    model in practice, as ``(type, [start, end])``. The text slice is preferred; the label's
    first element is the fallback when the offsets do not fit ``text``. Malformed labels yield
    ``("", 0, 0)``.
    """
    if not isinstance(label, (list, tuple)):
        return "", 0, 0
    try:
        label_fields = list(label)
        if len(label_fields) == 2 and isinstance(label_fields[1], (list, tuple)):
            label_fields = [label_fields[0], *label_fields[1]]
        if len(label_fields) < 3:
            return "", 0, 0
        first_field, start, end = label_fields[0], int(label_fields[1]), int(label_fields[2])
    except (TypeError, ValueError):
        return "", 0, 0
    span = ""
    if 0 <= start < end <= len(text):
        span = text[start:end].strip()
    entity = span or str(first_field).strip()
    return entity, start, end


def reactions_from_pdf_results(
    payload: dict,
) -> tuple[list[ExtractedReaction], list[ExtractedMolecule]]:
    """Flatten OpenChemIE multimodal reaction output into reactions and their molecules."""
    reactions: list[ExtractedReaction] = []
    molecules: list[ExtractedMolecule] = []
    if not isinstance(payload, dict):
        logger.warning("Ignoring malformed OpenChemIE reaction payload: expected a mapping")
        return reactions, molecules

    for figure in _mapping_entries(payload.get("figures"), "reaction figures"):
        figure_reactions, figure_molecules = _reactions_from_figure(figure)
        reactions.extend(figure_reactions)
        molecules.extend(figure_molecules)
    for page_block in _mapping_entries(payload.get("text"), "text reaction pages"):
        reactions.extend(_reactions_from_text_page(page_block))
    return reactions, molecules


def _reactions_from_figure(
    figure: dict,
) -> tuple[list[ExtractedReaction], list[ExtractedMolecule]]:
    """Parse the reactions drawn in one figure, plus a molecule record per participant."""
    reactions: list[ExtractedReaction] = []
    molecules: list[ExtractedMolecule] = []
    page = parse_page_number(figure.get("page"))
    for reaction in _mapping_entries(figure.get("reactions"), "figure reactions"):
        reactant_entries = _mapping_entries(reaction.get("reactants"), "reaction reactants")
        product_entries = _mapping_entries(reaction.get("products"), "reaction products")
        condition_entries = _mapping_entries(reaction.get("conditions"), "reaction conditions")
        conditions = join_text([item.get("text") for item in condition_entries if item.get("text")])
        reactions.append(
            ExtractedReaction(
                page=page,
                reactants=[str(item["smiles"]) for item in reactant_entries if item.get("smiles")],
                products=[str(item["smiles"]) for item in product_entries if item.get("smiles")],
                conditions=conditions,
                source="figure",
            )
        )
        for role, participants in (
            ("reaction_reactant", reactant_entries),
            ("reaction_product", product_entries),
        ):
            for participant in participants:
                smiles = str(participant.get("smiles") or "")
                if not smiles:
                    continue
                molecule = ExtractedMolecule(
                    smiles=smiles,
                    molfile=str(participant.get("molfile") or ""),
                    source=role,
                    page=page,
                    bbox=parse_bbox(participant.get("bbox")),
                    context=conditions,
                )
                molecules.append(enrich_molecule(molecule))
    return reactions, molecules


def _reactions_from_text_page(page_block: dict) -> list[ExtractedReaction]:
    """Parse the reactions that were found in the sentences of one text page."""
    reactions: list[ExtractedReaction] = []
    page = parse_page_number(page_block.get("page"))
    for sentence in _mapping_entries(page_block.get("reactions"), "reaction sentences"):
        sentence_text = " ".join(str(token) for token in sentence.get("tokens") or [])
        for reaction in _mapping_entries(sentence.get("reactions"), "text reactions"):
            conditions = join_text(reaction.get("Reaction") or reaction.get("conditions") or "")
            reactions.append(
                ExtractedReaction(
                    page=page,
                    reactants=_text_reaction_role_entries(reaction, "Reactants"),
                    products=_text_reaction_role_entries(reaction, "Products"),
                    conditions=conditions or sentence_text,
                    source="text",
                )
            )
    return reactions


def _text_reaction_role_entries(reaction: dict, role_key: str) -> list[str]:
    """List the compound strings of one role (``Reactants``/``Products``) in a text reaction."""
    role_value = reaction.get(role_key) or reaction.get(role_key.lower()) or []
    entries: list[str] = []
    items = role_value if isinstance(role_value, list) else [role_value]
    for item in items:
        if isinstance(item, (list, tuple)) and item:
            token = item[0]
            if isinstance(token, (list, tuple)):
                text = " ".join(str(part) for part in token)
            else:
                text = str(token)
            if text:
                entries.append(text)
        elif isinstance(item, str) and item.strip():
            entries.append(item.strip())
    return entries


def collapse_name_mentions(molecules: list[ExtractedMolecule]) -> list[ExtractedMolecule]:
    """Keep one record per chemical name mentioned in the text without a structure.

    A review names "gefitinib" dozens of times; the mentions become one record listing every
    page. A name that already labels a structure (drawn, or converted from a name) adds nothing
    and is dropped. Structures, and names with one, are kept as they are.
    """
    from .tables import normalize_label

    labelled = {
        normalize_label(part)
        for molecule in molecules
        if molecule.smiles or molecule.molfile
        for part in (molecule.identifier or "").split(";")
        if part.strip()
    }
    kept: list[ExtractedMolecule] = []
    by_name: dict[str, ExtractedMolecule] = {}
    for molecule in molecules:
        if molecule.smiles or molecule.molfile or not molecule.identifier:
            kept.append(molecule)
            continue
        name = normalize_label(molecule.identifier)
        if name in labelled:
            continue
        first = by_name.get(name)
        if first is None:
            by_name[name] = molecule
            kept.append(molecule)
            continue
        first.pages = sorted(set(first.page_numbers) | set(molecule.page_numbers))
        first.page = first.pages[0] if first.pages else first.page
    return kept
