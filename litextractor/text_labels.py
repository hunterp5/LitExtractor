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

"""Label figure structures with the text printed next to them in the PDF's text layer.

OpenChemIE's coreference model finds compound numbers drawn beside structures, but on real
documents it often finds none: journal figures label structures with drug names
("Gefitinib"), and patents print structures in table rows whose example number sits in
another column. Both labels are usually in the PDF's text layer (exact in digital PDFs, OCR
in scanned ones), so they are read from there by position:

- In a figure, a structure's label is the nearest short text just below it, overlapping it
  horizontally.
- In a table, it is the first compound number to the left of the structure in the same row.

A figure that is a picture (its region holds no text-layer text) is read with OCR instead,
and the same rules apply to what OCR finds.

Positions are PDF points with the origin at the bottom left, as pdfminer reports them.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from .models import ExtractedMolecule

logger = logging.getLogger(__name__)

Box = tuple[float, float, float, float]  # x1, y1, x2, y2 with y1 < y2 (PDF points)

#: OpenChemIE widens table regions by this many points on each side before reading them.
TABLE_PAD = 20.0

_CAPTION = re.compile(
    r"^(?:(?:fig(?:ure)?|scheme|table|chart)\.?\s*\d|\d+(?:\.\d+)+\.?\s)", re.IGNORECASE
)
_ATOM_TEXT = re.compile(
    r"^(?:H\d?)?(?:C|N|O|S|P|F|Cl|Br|I|B|Si|Se|Na|K|Li|Mg|Zn|Cu|Pd|Pt|Sn)(?:H\d?)?\d*[+-]?$"
    r"|^(?:CF3|OCF3|CN|NC|OMe|MeO|OEt|EtO|Me|Et|iPr|tBu|Ph|Bn|Boc|Ts|Ac|NO2|CO2H|COOH|R\d*'*|"
    r"[XYZ]|Ar|HCl|\d)$"
)
_COMPOUND_NUMBER = re.compile(r"^[A-Za-z]{0,3}\d{1,4}[a-z]?$")
_MAX_LABEL_CHARS = 40
_MAX_LABEL_WORDS = 5


@dataclass(frozen=True)
class TextLine:
    """One line of the text layer and where it sits."""

    box: Box
    text: str


@dataclass(frozen=True)
class FigurePlacement:
    """Where a figure image sits on its page.

    Attributes:
        page: Zero-based page index in the PDF the figure was detected in.
        box: The figure's region in PDF points, or None for a whole-page figure.
        in_table: True when the figure is a table region (structures printed in table rows).
    """

    page: int
    box: Box | None
    in_table: bool = False


def placement_from_openchemie(figure: dict) -> FigurePlacement | None:
    """Read a figure's page and region from an OpenChemIE figure result.

    Regions found as tables are widened by OpenChemIE before reading their text, while their
    image is not; the widening is undone so the region matches the image. A ``[0, 0, 1, 1]``
    box marks a whole-page figure.
    """
    page = figure.get("page")
    if not isinstance(page, int):
        return None
    raw = (figure.get("figure") or {}).get("bbox") or []
    in_table = (figure.get("table") or {}).get("content") is not None
    try:
        x1, y1, x2, y2 = (float(value) for value in raw[:4])
    except (TypeError, ValueError):
        return FigurePlacement(page, None, in_table)
    if (x1, y1, x2, y2) == (0.0, 0.0, 1.0, 1.0):
        return FigurePlacement(page, None, in_table)
    if in_table:
        x1, x2 = x1 + TABLE_PAD, x2 - TABLE_PAD
    box = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
    return FigurePlacement(page, box, in_table)


def molecule_box_on_page(figure_box: Box, molecule_bbox: Any) -> Box | None:
    """Map a molecule box normalized to its figure image (y down) to PDF points (y up)."""
    try:
        left, top, right, bottom = (float(value) for value in molecule_bbox[:4])
    except (TypeError, ValueError):
        return None
    fx1, fy1, fx2, fy2 = figure_box
    width, height = fx2 - fx1, fy2 - fy1
    return (fx1 + left * width, fy2 - bottom * height, fx1 + right * width, fy2 - top * height)


def page_text_lines(pdf_path: str, page_index: int) -> tuple[list[TextLine], Box | None]:
    """Return the text-layer lines of one page and the page's own box."""
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTTextContainer, LTTextLineHorizontal

    lines: list[TextLine] = []
    page_box = None
    for layout in extract_pages(pdf_path, page_numbers=[page_index]):
        page_box = tuple(layout.bbox)
        for element in layout:
            if not isinstance(element, LTTextContainer):
                continue
            for line in element:
                if isinstance(line, LTTextLineHorizontal):
                    text = " ".join(line.get_text().split())
                    if text:
                        lines.append(TextLine(tuple(line.bbox), text))
    return lines, page_box


def ocr_lines(image: Any, region: Box, reader: Any, min_confidence: float = 0.3) -> list[TextLine]:
    """Read the text in a figure image with EasyOCR, placed in PDF points within *region*."""
    import numpy as np

    pixels = np.asarray(image)
    if pixels.ndim < 2 or reader is None:
        return []
    height, width = pixels.shape[:2]
    x1, y1, x2, y2 = region
    lines = []
    for points, text, confidence in reader.readtext(pixels):
        text = " ".join(str(text).split())
        if not text or confidence < min_confidence:
            continue
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        box = (
            x1 + min(xs) / width * (x2 - x1),
            y2 - max(ys) / height * (y2 - y1),
            x1 + max(xs) / width * (x2 - x1),
            y2 - min(ys) / height * (y2 - y1),
        )
        lines.append(TextLine(box, text))
    return lines


def _inside(point: tuple[float, float], box: Box) -> bool:
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def _center(box: Box) -> tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def _is_label_text(text: str) -> bool:
    """True for short text that could name a structure (not a caption, sentence or atom)."""
    return (
        len(text) <= _MAX_LABEL_CHARS
        and len(text.split()) <= _MAX_LABEL_WORDS
        and not _CAPTION.match(text)
        and not _ATOM_TEXT.match(text)
        and not text.endswith((",", ";"))
    )


def labels_below(molecule_boxes: list[Box], lines: list[TextLine], region: Box | None) -> list[str]:
    """Pair each structure in a figure with the nearest label printed just below it.

    A candidate is short label-like text inside the figure region, not inside any structure
    (atom labels are text too), that overlaps the structure horizontally and sits at most
    half a structure height (or 25 pt) below it. Pairs are taken nearest first, so each label
    names one structure and each structure gets one label; "" where none fits.
    """
    candidates = [
        line
        for line in lines
        if _is_label_text(line.text)
        and (region is None or _inside(_center(line.box), _grow(region, 4)))
        and not any(_inside(_center(line.box), box) for box in molecule_boxes)
    ]
    scored = []
    for molecule_index, box in enumerate(molecule_boxes):
        width, height = box[2] - box[0], box[3] - box[1]
        for line_index, line in enumerate(candidates):
            overlaps = line.box[0] < box[2] + 0.1 * width and line.box[2] > box[0] - 0.1 * width
            gap = box[1] - line.box[3]
            line_height = line.box[3] - line.box[1]
            if not overlaps or gap < -0.5 * line_height or gap > max(0.5 * height, 25.0):
                continue
            offset = abs(_center(line.box)[0] - _center(box)[0])
            scored.append((max(gap, 0.0) + 0.25 * offset, molecule_index, line_index))
    labels = [""] * len(molecule_boxes)
    used_lines: set[int] = set()
    for _score, molecule_index, line_index in sorted(scored):
        if labels[molecule_index] or line_index in used_lines:
            continue
        labels[molecule_index] = candidates[line_index].text
        used_lines.add(line_index)
    return labels


def labels_in_rows(molecule_boxes: list[Box], lines: list[TextLine], region: Box | None) -> list[str]:
    """Label each structure in a table with the first compound number to its left, same row.

    The row is the structure's height, extended upward by half of it, because numbers sit
    at the top of a row while structures are often centred in it.
    """
    labels = []
    for box in molecule_boxes:
        height = box[3] - box[1]
        row_bottom, row_top = box[1], box[3] + 0.5 * height
        best: tuple[float, str] | None = None
        for line in lines:
            if region is not None and not _inside(_center(line.box), _grow(region, 4)):
                continue
            if line.box[2] > box[0] + 2 or not (line.box[1] < row_top and line.box[3] > row_bottom):
                continue
            first = line.text.split()[0]
            if not _COMPOUND_NUMBER.match(first):
                continue
            if best is None or line.box[0] < best[0]:
                best = (line.box[0], first)
        labels.append(best[1] if best else "")
    return labels


def _shrink(box: Box, fraction: float) -> Box:
    """*box* with *fraction* of its width and height removed from each side."""
    dx, dy = (box[2] - box[0]) * fraction, (box[3] - box[1]) * fraction
    return (box[0] + dx, box[1] + dy, box[2] - dx, box[3] - dy)


def _grow(box: Box, amount: float) -> Box:
    return (box[0] - amount, box[1] - amount, box[2] + amount, box[3] + amount)


def apply_text_layer_labels(
    molecules: list[ExtractedMolecule],
    placements: list[FigurePlacement | None],
    pdf_path: str,
    figure_images: list[Any] | None = None,
    ocr_reader: Any = None,
) -> int:
    """Label figure molecules from the text layer (or OCR); return how many got a label.

    ``placements[i]`` and ``figure_images[i]`` describe the figure whose molecules have
    ``figure_index == i``. A figure region without text-layer text is OCR'd with
    ``ocr_reader`` (an EasyOCR reader) when one is given. A label found here replaces one from
    the coreference model: in digital PDFs it is the exact printed text, not an OCR reading.
    """
    by_figure: dict[int, list[ExtractedMolecule]] = {}
    for molecule in molecules:
        if molecule.figure_index is not None and molecule.bbox is not None:
            by_figure.setdefault(molecule.figure_index, []).append(molecule)

    page_cache: dict[int, tuple[list[TextLine], Box | None]] = {}
    labelled = 0
    for figure_index, figure_molecules in sorted(by_figure.items()):
        placement = placements[figure_index] if figure_index < len(placements) else None
        if placement is None:
            continue
        if placement.page not in page_cache:
            try:
                page_cache[placement.page] = page_text_lines(pdf_path, placement.page)
            except Exception:
                logger.warning("Could not read the text layer of page %d", placement.page + 1,
                               exc_info=True)
                page_cache[placement.page] = ([], None)
        lines, page_box = page_cache[placement.page]
        region = placement.box or page_box
        if region is None:
            continue
        # Text in the region's inner part only: its edges include context the layout region
        # was widened by (paragraph lines, the caption), which says nothing about the figure.
        inner = _shrink(region, 0.1)
        if not any(_inside(_center(line.box), inner) for line in lines):
            image = figure_images[figure_index] if figure_images and figure_index < len(figure_images) else None
            try:
                lines = ocr_lines(image, region, ocr_reader) if image is not None else []
            except Exception:
                logger.warning("OCR of a figure on page %d failed", placement.page + 1,
                               exc_info=True)
                lines = []
        boxes = [molecule_box_on_page(region, molecule.bbox) for molecule in figure_molecules]
        kept = [(molecule, box) for molecule, box in zip(figure_molecules, boxes) if box]
        if not kept:
            continue
        finder = labels_in_rows if placement.in_table else labels_below
        found = finder([box for _, box in kept], lines, region)
        for (molecule, _box), label in zip(kept, found):
            if label:
                molecule.identifier = label
                labelled += 1
    return labelled
