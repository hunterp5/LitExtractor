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

"""Main-window smoke tests."""

from __future__ import annotations

from PySide6.QtGui import QPalette

from patentextractor.extraction import ExtractedMolecule, ExtractionResult, enrich_molecule
from patentextractor.ui.main_window import APP_NAME, MainWindow
from patentextractor.ui.molecule_table import render_structure_pixmap
from patentextractor.ui.theme import THEME_DARK, apply_application_theme, current_theme_name


def test_main_window_loads_molecules(qapp):  # noqa: ARG001
    w = MainWindow()
    rec = enrich_molecule(ExtractedMolecule(smiles="CCO", identifier="EtOH", page=1))
    result = ExtractionResult(pdf_path="demo.pdf", molecules=[rec], reactions=[])
    w._on_extract_finished(result)
    assert w._mol_table.molecule_model().rowCount() == 1
    assert w.windowTitle() == APP_NAME
    w.close()


def test_main_window_does_not_rank_results_twice(qapp, monkeypatch):
    import patentextractor.ui.molecule_table as molecule_table

    def unexpected_ranking(_molecules):
        raise AssertionError("already-ranked extraction results should not be ranked again")

    monkeypatch.setattr(molecule_table, "prioritize_molecules", unexpected_ranking)
    w = MainWindow()
    rec = enrich_molecule(ExtractedMolecule(smiles="CCO", identifier="EtOH", page=1))
    w._on_extract_finished(ExtractionResult(pdf_path="demo.pdf", molecules=[rec], reactions=[]))
    assert w._mol_table.molecule_model().rowCount() == 1
    w.close()


def test_main_window_theme_switch(qapp):
    w = MainWindow()
    apply_application_theme(qapp, THEME_DARK)
    w.refresh_theme()
    assert current_theme_name() == THEME_DARK
    assert w.palette().color(QPalette.ColorRole.Window).lightness() < 120
    assert w.menuBar().palette().color(QPalette.ColorRole.Window).lightness() < 120
    w.close()


def test_manual_checkbox_defaults_are_used(qapp):  # noqa: ARG001
    w = MainWindow()
    assert w._all_pages_chk.isChecked() is True
    assert w._all_structures_chk.isChecked() is True
    assert w._first_page_spin.isEnabled() is False
    assert w._pages_spin.isEnabled() is False
    assert w._max_mols_spin.isEnabled() is False
    assert w._crop_margin_spin.value() == 0.0
    opts = w._current_options()
    assert opts.figures is True
    assert opts.text is True
    assert opts.corefs is False
    assert opts.reactions is False
    assert opts.first_page == 1
    assert opts.num_pages is None
    assert opts.max_molecules is None
    assert opts.crop_margin == 0.0
    w._all_pages_chk.setChecked(False)
    assert w._first_page_spin.isEnabled() is True
    assert w._pages_spin.isEnabled() is True
    w._all_structures_chk.setChecked(False)
    assert w._max_mols_spin.isEnabled() is True
    w.close()


def test_structure_pixmap_tolerates_bad_valence(qapp):  # noqa: ARG001
    rec = ExtractedMolecule(smiles="C(C)(C)(C)(C)C")
    pix = render_structure_pixmap(rec)
    assert not pix.isNull()


def test_close_during_extraction_waits_for_worker(qapp):
    class RunningWorker:
        running = True
        interruption_requested = False

        def isRunning(self):
            return self.running

        def requestInterruption(self):
            self.interruption_requested = True

    window = MainWindow()
    worker = RunningWorker()
    window._worker = worker
    window.show()

    assert window.close() is False
    assert window.isVisible()
    assert worker.interruption_requested
    assert window._close_after_worker

    worker.running = False
    window._on_worker_thread_finished()

    assert not window.isVisible()


def test_worker_reports_cancellation_without_emitting_failure(qapp, monkeypatch):  # noqa: ARG001
    from PySide6.QtTest import QSignalSpy

    import patentextractor.workers.extract_worker as extract_worker
    from patentextractor.extraction import ExtractionCancelled
    from patentextractor.models import ExtractOptions

    def cancel_extraction(*_args, **_kwargs):
        raise ExtractionCancelled("Extraction cancelled.")

    monkeypatch.setattr(extract_worker, "extract_from_pdf", cancel_extraction)
    worker = extract_worker.ExtractWorker("unused.pdf", ExtractOptions())
    cancelled = QSignalSpy(worker.cancelled)
    failed = QSignalSpy(worker.failed)

    worker.start()
    assert worker.wait(5000)

    assert cancelled.count() == 1
    assert failed.count() == 0
