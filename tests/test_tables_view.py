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

"""The Tables tab, table columns on the Molecules table and the Table data card."""

from __future__ import annotations

from PySide6.QtCore import Qt

from litextractor.chemistry import enrich_molecule
from litextractor.models import ExtractedMolecule, ExtractedTable, ExtractionResult
from litextractor.table_review import confirm_link, toggle_shown_column
from litextractor.tables import link_table_rows
from litextractor.ui.extraction_result_tab import TABLES_TAB, ExtractionResultTab
from litextractor.ui.main_window import MainWindow
from litextractor.ui.molecule_table import HEADERS


def egfr_result():
    gefitinib = enrich_molecule(ExtractedMolecule(smiles="CCO", identifier="Gefitinib", page=3))
    erlotinib = enrich_molecule(ExtractedMolecule(smiles="CCN", identifier="Erlotinib", page=3))
    table = ExtractedTable(
        id="T1",
        title="Table 3. EGFR inhibitors and their approvals",
        pages=[3],
        columns=["Name (Trade Name)", "Targets", "Year"],
        rows=[["Gefitinib (Iressa)", "EGFR", "2003"], ["Erlotinib (Tarceva)", "EGFR", "2004"],
              ["Osimertinib (Tagrisso)", "EGFR T790M", "2015"]],
    )
    result = ExtractionResult("egfr.pdf", [gefitinib, erlotinib], [], tables=[table])
    result.table_links = link_table_rows([table], result.molecules)
    return result, table, gefitinib, erlotinib


def link_cells(tab):
    model = tab.tables_view.grid_model
    return [model.data(model.index(row, 0)) for row in range(model.rowCount())]


def test_tables_tab_lists_tables_with_link_status_per_row(qapp):
    result, _table, _, _ = egfr_result()
    tab = ExtractionResultTab()

    tab.set_result(result)

    assert tab.tabs.tabText(TABLES_TAB) == "Tables (1)"
    assert tab.tables_view.table_combo.itemText(0) == "Table 3  ·  p. 3  ·  2/3 rows linked"
    assert tab.tables_view.summary_label.text() == "2 of 3 rows linked"
    model = tab.tables_view.grid_model
    assert [model.headerData(c, Qt.Horizontal) for c in range(model.columnCount())] == [
        "Structure", "Name (Trade Name) (key)", "Targets", "Year",
    ]
    assert link_cells(tab) == ["Gefitinib", "Erlotinib", "—"]


def test_editing_a_key_cell_rematches_and_editing_values_updates_shown_columns(qapp):
    result, table, gefitinib, _ = egfr_result()
    tab = ExtractionResultTab()
    tab.set_result(result)
    model = tab.tables_view.grid_model
    changes = []
    tab.table_data_changed.connect(lambda: changes.append(True))

    toggle_shown_column(result, "T1", 2)
    tab.tables_view.table_data_changed.emit()
    model.setData(model.index(2, 1), "Gefitinib")
    model.setData(model.index(0, 3), "2002")

    assert link_cells(tab) == ["Gefitinib", "Erlotinib", "Gefitinib"]
    molecules = tab.molecule_table.molecule_model()
    assert molecules.headerData(len(HEADERS), Qt.Horizontal) == "Table 3 · Year"
    row = molecules.row_of(gefitinib.id)
    assert molecules.data(molecules.index(row, len(HEADERS))) == "2002; 2015"
    assert table.rows[0][2] == "2002" and len(changes) == 3


def test_confirmed_rows_show_a_tick_and_link_to_their_structure(qapp):
    result, _table, _, erlotinib = egfr_result()
    confirm_link(result, "T1", 1, erlotinib.id)
    tab = ExtractionResultTab()
    tab.set_result(result)

    tab.tables_view.show_molecule_requested.emit(erlotinib.id)

    assert link_cells(tab)[1] == "✓ Erlotinib"
    assert tab.tabs.currentIndex() == 0
    (selected,) = tab.molecule_table.selectionModel().selectedRows()
    assert tab.molecule_table.molecule_model().molecule_at(selected.row()) is erlotinib


def test_detail_pane_lists_linked_rows_and_opens_them_in_the_tables_tab(qapp):
    result, _table, gefitinib, _ = egfr_result()
    window = MainWindow()
    window._on_extract_finished(result)
    tab = window._active_result_tab
    tab.molecule_table.selectRow(tab.molecule_table.molecule_model().row_of(gefitinib.id))

    text = window._detail_tables.text()
    assert not window._detail_tables_card.isHidden()
    assert 'href="table:T1:0"' in text and "Table 3</b>, row 1</a> · suggested" in text
    assert "Targets:</span> EGFR" in text and "Iressa" not in text  # key cell left out

    window._open_table_row("table:T1:0")
    assert tab.tabs.currentIndex() == TABLES_TAB
    assert [index.row() for index in tab.tables_view.grid.selectionModel().selectedRows()] == [0]
    assert "1 table(s)" in window.status_label.text()
    window.close()


def test_results_without_tables_explain_why(qapp):
    tab = ExtractionResultTab()

    tab.set_result(ExtractionResult("scan.pdf", [], []))

    assert tab.tabs.tabText(TABLES_TAB) == "Tables (0)"
    assert tab.tables_view._stack.currentWidget() is tab.tables_view.empty_label


def test_double_clicking_a_table_image_opens_it_zoomable(qapp):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImage

    from litextractor.ui.dialogs.image_viewer import ClickableImage

    image = QImage(800, 400, QImage.Format_RGB32)
    image.fill(Qt.white)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    result, table, _, _ = egfr_result()
    table.crops_png = [bytes(data), bytes(data)]
    tab = ExtractionResultTab()
    tab.set_result(result)
    opened = []
    original = tab.tables_view.open_crop
    tab.tables_view.open_crop = lambda *args: opened.append(original(*args))

    crops = tab.tables_view.crop_container.findChildren(ClickableImage)
    crops[1].double_clicked.emit()

    (viewer,) = opened
    assert viewer.windowTitle() == "Table 3 · p. 3 · image 2 of 2"
    assert viewer.isVisible() and not viewer.isModal()
    viewer.set_zoom(1.0)
    assert viewer.image_label.pixmap().width() == 800 and viewer.zoom_label.text() == "100%"
    viewer.zoom_by(1.25)
    assert viewer.image_label.pixmap().width() == 1000
    viewer.zoom_by(100)
    assert viewer.zoom == 8.0
    viewer.fit_to_window()
    assert viewer.image_label.pixmap().width() <= viewer.scroll_area.viewport().width()
    viewer.close()


def test_reactions_tab_shows_only_when_reactions_were_extracted(qapp):
    from litextractor.models import ExtractedReaction

    without, asked, found = ExtractionResultTab(), ExtractionResultTab(), ExtractionResultTab()

    without.set_result(ExtractionResult("a.pdf", [], []))
    asked.set_result(ExtractionResult("b.pdf", [], [], reactions_requested=True))
    reaction = ExtractedReaction(page=2, reactants=["CCO"], products=["CC=O"], conditions="")
    found.set_result(ExtractionResult("c.pdf", [], [reaction]))

    assert not without.tabs.isTabVisible(1)
    assert asked.tabs.isTabVisible(1) and asked.tabs.tabText(1) == "Reactions (0)"
    assert found.tabs.isTabVisible(1)
    assert without.tabs.isTabVisible(TABLES_TAB)
