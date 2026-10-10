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

"""Link OpenChemIE coreference labels to extracted figure molecules."""

from __future__ import annotations

import logging
from numbers import Integral
from typing import Any

from .extraction_results import join_text, parse_bbox, parse_page_number
from .models import ExtractedMolecule

logger = logging.getLogger(__name__)

# A figure molecule only receives a label when its box overlaps the coreference box this much.
MIN_BOX_OVERLAP = 0.15


def bbox_intersection_over_union(
    first_box: tuple[float, ...] | None, second_box: tuple[float, ...] | None
) -> float:
    """Return the overlap of two ``(left, top, right, bottom)`` boxes: area shared / area covered.

    Missing or malformed boxes, and boxes that do not overlap, score 0.0.
    """
    if first_box is None or second_box is None or len(first_box) < 4 or len(second_box) < 4:
        return 0.0
    first_left, first_top, first_right, first_bottom = first_box[:4]
    second_left, second_top, second_right, second_bottom = second_box[:4]
    overlap_width = max(0.0, min(first_right, second_right) - max(first_left, second_left))
    overlap_height = max(0.0, min(first_bottom, second_bottom) - max(first_top, second_top))
    intersection_area = overlap_width * overlap_height
    if intersection_area <= 0:
        return 0.0
    first_area = max(0.0, first_right - first_left) * max(0.0, first_bottom - first_top)
    second_area = max(0.0, second_right - second_left) * max(0.0, second_bottom - second_top)
    union_area = first_area + second_area - intersection_area
    return intersection_area / union_area if union_area else 0.0


def apply_coref_identifiers(
    molecules: list[ExtractedMolecule], coreference_figures: list[dict]
) -> None:
    """Attach identifier text from coreference pairs to overlapping figure molecules.

    Each pair links a molecule box to a label box on the same page. The label becomes the
    identifier of the figure molecule that overlaps the molecule box the most. Malformed
    entries are logged and skipped individually.
    """
    figure_molecules_by_page: dict[int | None, list[ExtractedMolecule]] = {}
    for molecule in molecules:
        if molecule.source == "figure":
            figure_molecules_by_page.setdefault(molecule.page, []).append(molecule)

    for figure in coreference_figures or []:
        if not isinstance(figure, dict):
            logger.warning("Ignoring malformed OpenChemIE coreference figure")
            continue
        raw_page = figure.get("page")
        page = parse_page_number(raw_page)
        if raw_page is not None and page is None:
            continue
        boxes = figure.get("bboxes")
        if not isinstance(boxes, (list, tuple)):
            logger.warning("Ignoring malformed OpenChemIE coreference boxes on page %r", page)
            continue
        pairs = figure.get("corefs") or []
        if not isinstance(pairs, (list, tuple)):
            logger.warning("Ignoring malformed OpenChemIE coreference pairs on page %r", page)
            continue
        page_molecules = figure_molecules_by_page.get(page, [])
        for pair in pairs:
            box_pair = _boxes_of_pair(pair, boxes)
            if box_pair is not None:
                _label_best_overlapping_molecule(page_molecules, *box_pair)


def _boxes_of_pair(pair: Any, boxes: list | tuple) -> tuple[dict, dict] | None:
    """Return the ``(molecule_box, label_box)`` of a coreference pair, or None if malformed."""
    if not isinstance(pair, (list, tuple)) or len(pair) < 2:
        logger.warning("Ignoring malformed OpenChemIE coreference pair %r", pair)
        return None
    molecule_index = _coreference_index(pair[0])
    label_index = _coreference_index(pair[1])
    if molecule_index is None or label_index is None:
        logger.warning("Ignoring non-integer OpenChemIE coreference pair %r", pair)
        return None
    if not (0 <= molecule_index < len(boxes) and 0 <= label_index < len(boxes)):
        logger.warning("Ignoring out-of-range OpenChemIE coreference pair %r", pair)
        return None
    molecule_box, label_box = boxes[molecule_index], boxes[label_index]
    if not isinstance(molecule_box, dict) or not isinstance(label_box, dict):
        logger.warning("Ignoring coreference pair with malformed boxes %r", pair)
        return None
    return molecule_box, label_box


def _label_best_overlapping_molecule(
    page_molecules: list[ExtractedMolecule], molecule_box: dict, label_box: dict
) -> None:
    """Give the label text to the molecule that best overlaps ``molecule_box`` (if any)."""
    label = join_text(label_box.get("text") or label_box.get("category") or "")
    if not label or label.startswith("["):
        return
    molecule_bbox = parse_bbox(molecule_box.get("bbox"))
    best_match: ExtractedMolecule | None = None
    best_overlap = MIN_BOX_OVERLAP
    for molecule in page_molecules:
        overlap = bbox_intersection_over_union(molecule.bbox, molecule_bbox)
        if overlap > best_overlap:
            best_overlap = overlap
            best_match = molecule
    if best_match is None:
        return
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
