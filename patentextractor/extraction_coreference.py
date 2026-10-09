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

"""Link OpenChemIE coreference labels to extracted figure molecules."""

from __future__ import annotations

import logging
from numbers import Integral
from typing import Any

from .extraction_results import _as_bbox, _join_text, _page_number
from .models import ExtractedMolecule

logger = logging.getLogger(__name__)


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


def apply_coref_identifiers(
    molecules: list[ExtractedMolecule], coref_figures: list[dict]
) -> None:
    """Attach identifier text from coreference pairs to overlapping figure molecules."""
    page_molecules: dict[int | None, list[ExtractedMolecule]] = {}
    for molecule in molecules:
        if molecule.source != "figure":
            continue
        page_molecules.setdefault(molecule.page, []).append(molecule)

    for figure in coref_figures or []:
        if not isinstance(figure, dict):
            logger.warning("Ignoring malformed OpenChemIE coreference figure")
            continue
        raw_page = figure.get("page")
        page = _page_number(raw_page)
        if raw_page is not None and page is None:
            continue
        raw_bboxes = figure.get("bboxes")
        if not isinstance(raw_bboxes, (list, tuple)):
            logger.warning("Ignoring malformed OpenChemIE coreference boxes on page %r", page)
            continue
        candidates = page_molecules.get(page, [])
        pairs = figure.get("corefs") or []
        if not isinstance(pairs, (list, tuple)):
            logger.warning("Ignoring malformed OpenChemIE coreference pairs on page %r", page)
            continue
        for pair in pairs:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                logger.warning("Ignoring malformed OpenChemIE coreference pair %r", pair)
                continue
            try:
                molecule_index = _coreference_index(pair[0])
                identifier_index = _coreference_index(pair[1])
            except (TypeError, ValueError, OverflowError):
                logger.warning("Ignoring non-integer OpenChemIE coreference pair %r", pair)
                continue
            if molecule_index is None or identifier_index is None:
                logger.warning("Ignoring non-integer OpenChemIE coreference pair %r", pair)
                continue
            if (
                molecule_index < 0
                or identifier_index < 0
                or molecule_index >= len(raw_bboxes)
                or identifier_index >= len(raw_bboxes)
            ):
                logger.warning("Ignoring out-of-range OpenChemIE coreference pair %r", pair)
                continue
            molecule_box = raw_bboxes[molecule_index]
            identifier_box = raw_bboxes[identifier_index]
            if not isinstance(molecule_box, dict) or not isinstance(identifier_box, dict):
                logger.warning("Ignoring coreference pair with malformed boxes %r", pair)
                continue
            label = _join_text(identifier_box.get("text") or identifier_box.get("category") or "")
            if not label or label.startswith("["):
                continue
            best_match: ExtractedMolecule | None = None
            best_iou = 0.15
            for molecule in candidates:
                iou = _bbox_iou(molecule.bbox, _as_bbox(molecule_box.get("bbox")))
                if iou > best_iou:
                    best_iou = iou
                    best_match = molecule
            if best_match is not None:
                if best_match.identifier and label not in best_match.identifier:
                    best_match.identifier = f"{best_match.identifier}; {label}"
                else:
                    best_match.identifier = label


def _coreference_index(value: Any) -> int | None:
    """Accept integer-like coreference indexes but reject booleans and fractional values."""
    if isinstance(value, bool):
        return None
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None