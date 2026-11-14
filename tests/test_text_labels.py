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

"""Labelling structures from the text printed beside them (text layer, or OCR for pictures)."""

from __future__ import annotations

import numpy as np
import pytest

from litextractor import text_labels
from litextractor.models import ExtractedMolecule
from litextractor.text_labels import (
    FigurePlacement,
    TextLine,
    apply_text_layer_labels,
    labels_below,
    labels_in_rows,
    molecule_box_on_page,
    ocr_lines,
    placement_from_openchemie,
)


def test_placement_undoes_table_padding_and_reads_whole_page_figures():
    figure = {"page": 3, "figure": {"bbox": [100, 400, 300, 100]}}
    table = {"page": 3, "figure": {"bbox": [80, 100, 320, 400]}, "table": {"content": {}}}
    whole_page = {"page": 0, "figure": {"bbox": [0, 0, 1, 1]}}

    assert placement_from_openchemie(figure) == FigurePlacement(3, (100, 100, 300, 400), False)
    assert placement_from_openchemie(table) == FigurePlacement(3, (100, 100, 300, 400), True)
    assert placement_from_openchemie(whole_page) == FigurePlacement(0, None, False)
    assert placement_from_openchemie({"figure": {}}) is None


def test_molecule_box_flips_image_coordinates_into_pdf_points():
    # Top-left quarter of the image is the top-left quarter of the region (PDF y points up).
    assert molecule_box_on_page((100, 100, 300, 500), (0, 0, 0.5, 0.25)) == (100, 400, 200, 500)
    assert molecule_box_on_page((100, 100, 300, 500), None) is None


def test_each_structure_takes_the_nearest_label_below_it_not_captions_or_atoms():
    left, right = (100, 300, 200, 400), (250, 300, 350, 400)
    lines = [
        TextLine((140, 340, 150, 350), "N"),               # an atom label inside the structure
        TextLine((130, 285, 170, 295), "Gefitinib"),
        TextLine((280, 285, 320, 295), "Erlotinib"),
        TextLine((280, 230, 320, 240), "Afatinib"),         # further down: the next row's label
        TextLine((100, 260, 350, 270), "Figure 1. First-generation EGFR inhibitors"),
    ]

    assert labels_below([left, right], lines, (90, 220, 360, 410)) == ["Gefitinib", "Erlotinib"]


def test_a_label_names_only_one_structure_and_text_outside_the_figure_is_ignored():
    upper, lower = (100, 300, 200, 400), (100, 200, 200, 270)
    lines = [TextLine((130, 285, 170, 295), "12a"), TextLine((130, 150, 170, 160), "12b")]

    # "12b" lies outside the figure region, so the lower structure stays unlabelled.
    assert labels_below([upper, lower], lines, (90, 180, 210, 410)) == ["12a", ""]


def test_table_structures_take_the_leftmost_compound_number_in_their_row():
    first_row, second_row = (200, 600, 300, 680), (200, 480, 300, 560)
    lines = [
        TextLine((60, 670, 80, 680), "281"),
        TextLine((100, 670, 160, 680), "D46 12"),  # another number, further right
        TextLine((60, 550, 80, 560), "282"),
        TextLine((320, 550, 360, 560), "283"),     # right of the structure: another column
    ]

    assert labels_in_rows([first_row, second_row], lines, None) == ["281", "282"]


class FakeReader:
    """EasyOCR stand-in returning fixed detections in image pixels."""

    def __init__(self, detections):
        self.detections = detections
        self.calls = 0

    def readtext(self, pixels):
        del pixels
        self.calls += 1
        return self.detections


def test_ocr_lines_are_placed_in_pdf_points_and_low_confidence_reads_dropped():
    reader = FakeReader([
        ([[50, 0], [150, 0], [150, 10], [50, 10]], "Gefitinib", 0.9),
        ([[0, 90], [10, 90], [10, 100], [0, 100]], "x", 0.1),
    ])
    image = np.zeros((100, 200, 3), dtype=np.uint8)  # 2 px per point both ways

    (line,) = ocr_lines(image, (100, 100, 200, 150), reader)

    assert line == TextLine((125, 145, 175, 150), "Gefitinib")


# A figure at (100, 100)-(300, 400) whose one structure sits at (150, 250)-(250, 370) on the page.
REGION = (100, 100, 300, 400)
STRUCTURE_BBOX = (0.25, 0.1, 0.75, 0.5)


def _figure_molecule():
    return ExtractedMolecule(smiles="C", identifier="Ia", figure_index=0, bbox=STRUCTURE_BBOX)


@pytest.fixture
def page_lines(monkeypatch):
    """Serve the given text-layer lines as the page's text."""
    def install(lines):
        monkeypatch.setattr(text_labels, "page_text_lines",
                            lambda pdf, page: (lines, (0, 0, 612, 792)))
    return install


def test_text_layer_label_replaces_the_coreference_label(page_lines):
    page_lines([TextLine((180, 235, 220, 245), "1a")])
    molecule = _figure_molecule()
    reader = FakeReader([])

    count = apply_text_layer_labels([molecule], [FigurePlacement(2, REGION)], "doc.pdf",
                                    [np.zeros((300, 200))], reader)

    assert count == 1 and molecule.identifier == "1a"
    assert reader.calls == 0


def test_picture_figures_are_ocrd_even_when_context_text_lines_their_edges(page_lines):
    # The layout region is widened for context, so body text and the caption reach its edges
    # even when the figure itself is a picture with no text layer.
    page_lines([
        TextLine((100, 392, 300, 400), "is found as a co-crystallized ligand with the kinase"),
        TextLine((100, 102, 300, 110), "Figure 1. First-generation EGFR inhibitors"),
    ])
    molecule = _figure_molecule()
    reader = FakeReader([([[80, 155], [120, 155], [120, 165], [80, 165]], "Gefitinib", 0.95)])

    count = apply_text_layer_labels([molecule], [FigurePlacement(2, REGION)], "doc.pdf",
                                    [np.zeros((300, 200))], reader)

    assert reader.calls == 1
    assert count == 1 and molecule.identifier == "Gefitinib"


def test_without_a_reader_or_placement_the_coreference_label_is_kept(page_lines):
    page_lines([])
    placed, unplaced = _figure_molecule(), _figure_molecule()
    unplaced.figure_index = 1

    count = apply_text_layer_labels([placed, unplaced], [FigurePlacement(0, REGION), None],
                                    "doc.pdf", [np.zeros((300, 200))], None)

    assert count == 0 and placed.identifier == unplaced.identifier == "Ia"
