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

"""Main-window smoke tests."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QFrame, QLabel, QMessageBox, QScrollArea

from litextractor.chemistry import enrich_molecule
from litextractor.models import ExtractedMolecule, ExtractionResult
from litextractor.ui.main_window import MainWindow
from litextractor.ui.molecule_table import render_structure_pixmap


def test_startup_welcome_transitions_through_loading_to_results(qapp):
    window = MainWindow()
    window.show()
    qapp.processEvents()

    assert window._result_tabs.count() == 0
    assert window._results_stack.currentWidget() is window._startup_page
    assert window._startup_page.isVisible()
    assert window._result_tabs.isHidden()
    assert window._detail_panel.isHidden()
    assert "Open a patent PDF" in window._startup_page.message_label.text()
    assert window._startup_page.message_label.alignment() == Qt.AlignCenter
    assert window._startup_page.findChildren(QLabel) == [window._startup_page.message_label]

    window._extraction_controller.handle_progress("Loading OpenChemIE models…")
    assert window._startup_page.message_label.text() == "Loading OpenChemIE models…"

    molecule = enrich_molecule(ExtractedMolecule(smiles="CCO", identifier="EtOH"))
    window._on_extract_finished(
        ExtractionResult(pdf_path="demo.pdf", molecules=[molecule], reactions=[])
    )
    assert window._results_stack.currentWidget() is window._result_tabs
    assert not window._detail_panel.isHidden()
    window.close()


def test_detail_pane_hides_missing_crop_and_aligns_metadata(qapp):
    window = MainWindow()
    assert window._detail_panel.findChild(QScrollArea) is not None
    assert window._detail_panel.findChild(QLabel, "DetailPanelTitle") is None
    cards = window._detail_panel.findChildren(QFrame, "DetailCard")
    assert len(cards) == 3
    card_titles = {
        label.text()
        for label in window._detail_panel.findChildren(QLabel, "DetailCardTitle")
    }
    assert card_titles == {"Chemical structure", "Patent crop", "Molecule information"}
    molecule = enrich_molecule(
        ExtractedMolecule(smiles="CCO", identifier="EtOH", page=2, source="text")
    )

    window._on_extract_finished(
        ExtractionResult(pdf_path="demo.pdf", molecules=[molecule], reactions=[])
    )

    assert window._detail_crop_card.isHidden()
    assert window._detail_values["Identifier"].text() == "EtOH"
    assert window._detail_values["Page"].text() == "2"
    assert window._detail_values["Source"].text() == "text"
    assert window._detail_values["Formula"].text() == "C2H6O"
    window.close()


def test_extractions_create_separate_tabs_and_export_uses_active_table(
    qapp, monkeypatch, tmp_path
):
    import litextractor.ui.main_window as main_window

    window = MainWindow()
    first_molecule = enrich_molecule(ExtractedMolecule(smiles="CCO", identifier="first"))
    second_molecule = enrich_molecule(
        ExtractedMolecule(smiles="CC(=O)C", identifier="second")
    )
    first_result = ExtractionResult(
        pdf_path="first.pdf", molecules=[first_molecule], reactions=[]
    )
    second_result = ExtractionResult(
        pdf_path="second.pdf", molecules=[second_molecule], reactions=[]
    )
    exported: list[ExtractedMolecule] = []
    monkeypatch.setattr(
        main_window.QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(tmp_path / "active.csv"), ""),
    )
    monkeypatch.setattr(
        main_window,
        "write_csv",
        lambda _path, molecules: exported.extend(molecules),
    )

    window._on_extract_finished(first_result)
    first_tab = window._active_result_tab
    window._on_extract_finished(second_result)

    assert window._result_tabs.count() == 2
    assert window._result_tabs.tabText(0) == "first.pdf"
    assert window._result_tabs.tabText(1) == "second.pdf"
    assert first_tab is not window._active_result_tab
    assert window._active_result_tab.result is second_result

    window._result_tabs.setCurrentIndex(0)
    assert window._active_result_tab.result is first_result
    window.export_csv()
    assert exported == [first_molecule]
    window.close()


def test_result_tab_deletion_requires_confirmation(qapp, monkeypatch):
    window = MainWindow()
    window._on_extract_finished(
        ExtractionResult(pdf_path="first.pdf", molecules=[], reactions=[])
    )
    window._on_extract_finished(
        ExtractionResult(pdf_path="second.pdf", molecules=[], reactions=[])
    )
    prompts: list[tuple[str, str]] = []

    def decline(_parent, title, message, *_args):
        prompts.append((title, message))
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, "question", decline)
    window._confirm_delete_result_tab(0)
    assert window._result_tabs.count() == 2
    assert prompts and "Delete 'first.pdf'" in prompts[0][1]

    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    window._confirm_delete_result_tab(0)
    assert window._result_tabs.count() == 1
    assert window._result_tabs.tabText(0) == "second.pdf"
    assert window._active_result_tab.result.pdf_path == "second.pdf"
    window.close()


def test_result_tab_context_menu_targets_right_clicked_tab(qapp, monkeypatch):
    import litextractor.ui.main_window as main_window

    window = MainWindow()
    window._on_extract_finished(
        ExtractionResult(pdf_path="first.pdf", molecules=[], reactions=[])
    )
    window._on_extract_finished(
        ExtractionResult(pdf_path="second.pdf", molecules=[], reactions=[])
    )
    window.show()
    qapp.processEvents()
    requested_deletions: list[int] = []

    class FakeMenu:
        def __init__(self, _parent):
            self.action = object()

        def addAction(self, _label):
            return self.action

        def exec(self, _position):
            return self.action

    monkeypatch.setattr(main_window, "QMenu", FakeMenu)
    monkeypatch.setattr(window, "_confirm_delete_result_tab", requested_deletions.append)
    click_position = window._result_tabs.tabBar().tabRect(1).center()

    window._show_result_tab_context_menu(QPoint(click_position))

    assert requested_deletions == [1]
    window.close()


def test_main_window_does_not_rank_results_twice(qapp, monkeypatch):
    import litextractor.ui.molecule_table as molecule_table

    def unexpected_ranking(_molecules):
        raise AssertionError("already-ranked extraction results should not be ranked again")

    monkeypatch.setattr(molecule_table, "prioritize_molecules", unexpected_ranking)
    w = MainWindow()
    molecule = enrich_molecule(ExtractedMolecule(smiles="CCO", identifier="EtOH", page=1))
    w._on_extract_finished(
        ExtractionResult(pdf_path="demo.pdf", molecules=[molecule], reactions=[])
    )
    assert w._active_molecule_table.molecule_model().rowCount() == 1
    w.close()


def test_cuda_probe_runs_in_background_and_updates_device_selector(
    qapp, monkeypatch
):  # noqa: ARG001
    import threading

    import litextractor.workers.cuda_probe_worker as cuda_probe_worker

    probe_started = threading.Event()
    release_probe = threading.Event()

    def delayed_cuda_probe() -> bool:
        probe_started.set()
        assert release_probe.wait(5)
        return True

    monkeypatch.setattr(cuda_probe_worker, "cuda_available", delayed_cuda_probe)
    window = MainWindow()
    assert window._device_combobox.count() == 1
    assert window._device_combobox.currentData() == "cpu"
    assert not probe_started.is_set()

    window.show()
    window.start_cuda_probe()
    assert probe_started.wait(5)
    assert window._device_combobox.count() == 1

    worker = window._cuda_worker
    assert worker is not None
    release_probe.set()
    assert worker.wait(5000)
    qapp.processEvents()

    assert window._device_combobox.findData("cuda") >= 0
    assert window._device_combobox.currentData() == "cuda"
    window.close()


def test_cuda_probe_preserves_manual_cpu_selection(qapp):  # noqa: ARG001
    window = MainWindow()
    window._device_combobox.activated.emit(0)

    window._on_cuda_probe_finished(True)

    assert window._device_combobox.findData("cuda") >= 0
    assert window._device_combobox.currentData() == "cpu"
    window.close()


def test_manual_checkbox_defaults_are_used(qapp):  # noqa: ARG001
    w = MainWindow()
    assert w._all_pages_checkbox.isChecked() is True
    assert w._all_structures_checkbox.isChecked() is True
    assert w._first_page_spinbox.isEnabled() is False
    assert w._page_count_spinbox.isEnabled() is False
    assert w._crop_margin_spinbox.value() == 0.0
    options = w._current_options()
    assert options.figures is True
    assert options.text is True
    assert w._corefs_checkbox.isChecked() is True
    assert options.corefs is True
    assert options.reactions is False
    assert options.first_page == 1
    assert options.num_pages is None
    assert options.max_molecules is None
    assert options.crop_margin == 0.0
    w._all_pages_checkbox.setChecked(False)
    assert w._first_page_spinbox.isEnabled() is True
    assert w._page_count_spinbox.isEnabled() is True
    w._all_structures_checkbox.setChecked(False)
    assert w._max_structures_spinbox.isEnabled() is True
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
    controller = window._extraction_controller
    worker = RunningWorker()
    controller.worker = worker
    window.show()

    assert window.close() is False
    assert window.isVisible()
    assert worker.interruption_requested
    assert controller.close_after_worker

    worker.running = False
    controller.handle_worker_thread_finished()

    assert not window.isVisible()


def test_worker_reports_cancellation_without_emitting_failure(qapp, monkeypatch):  # noqa: ARG001
    from PySide6.QtTest import QSignalSpy

    import litextractor.extraction as extraction
    import litextractor.workers.extract_worker as extract_worker
    from litextractor.extraction import ExtractionCancelled
    from litextractor.models import ExtractOptions

    def cancel_extraction(*_args, **_kwargs):
        raise ExtractionCancelled("Extraction cancelled.")

    monkeypatch.setattr(extraction, "extract_from_pdf", cancel_extraction)
    worker = extract_worker.ExtractWorker("unused.pdf", ExtractOptions())
    cancelled = QSignalSpy(worker.cancelled)
    failed = QSignalSpy(worker.failed)

    worker.start()
    assert worker.wait(5000)

    assert cancelled.count() == 1
    assert failed.count() == 0
