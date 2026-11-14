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

"""Extracting several PDFs in one go."""

from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QMessageBox

from litextractor.chemistry import enrich_molecule
from litextractor.models import ExtractedMolecule, ExtractionResult, ExtractOptions
from litextractor.ui.main_window import MainWindow, pdfs_in_folder


def test_worker_extracts_each_pdf_in_turn_and_continues_past_failures(qapp, monkeypatch):
    from PySide6.QtTest import QSignalSpy

    import litextractor.extraction as extraction
    from litextractor.workers.extract_worker import ExtractWorker

    def extract(pdf_path, options, *, progress, should_cancel):
        del options, should_cancel
        progress("Loading…")
        if pdf_path == "broken.pdf":
            raise RuntimeError("not a PDF")
        return ExtractionResult(pdf_path, [], [])

    monkeypatch.setattr(extraction, "extract_from_pdf", extract)
    worker = ExtractWorker(["a.pdf", "broken.pdf", "c.pdf"], ExtractOptions())
    finished, failed = QSignalSpy(worker.finished_ok), QSignalSpy(worker.failed)
    pdf_failed, done = QSignalSpy(worker.pdf_failed), QSignalSpy(worker.batch_finished)
    progress = QSignalSpy(worker.progress)

    worker.start()
    assert worker.wait(5000)

    assert [finished.at(i)[0].pdf_path for i in range(finished.count())] == ["a.pdf", "c.pdf"]
    assert failed.count() == 0
    assert pdf_failed.at(0) == ["broken.pdf", "not a PDF"]
    assert done.at(0) == [2, 3]
    assert progress.at(0) == ["[1/3] a.pdf: Loading…"]


def test_a_single_pdf_failure_is_still_reported_as_a_failure(qapp, monkeypatch):
    from PySide6.QtTest import QSignalSpy

    import litextractor.extraction as extraction
    from litextractor.workers.extract_worker import ExtractWorker

    def fail(*_args, **_kwargs):
        raise RuntimeError("Poppler is needed")

    monkeypatch.setattr(extraction, "extract_from_pdf", fail)
    worker = ExtractWorker("only.pdf", ExtractOptions())
    failed, done = QSignalSpy(worker.failed), QSignalSpy(worker.batch_finished)

    worker.start()
    assert worker.wait(5000)

    assert failed.at(0) == ["Poppler is needed"] and done.count() == 0


def test_folder_lists_its_own_pdfs_by_name(tmp_path):
    for name in ("b.PDF", "a.pdf", ".hidden.pdf", "notes.txt"):
        (tmp_path / name).write_text("")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.pdf").write_text("")

    assert [p.rsplit("/", 1)[-1] for p in pdfs_in_folder(tmp_path)] == ["a.pdf", "b.PDF"]


def test_opening_a_folder_selects_its_pdfs_and_a_batch_runs_them_all(qapp, monkeypatch, tmp_path):
    for name in ("one.pdf", "two.pdf", "three.pdf", "four.pdf"):
        (tmp_path / name).write_text("")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_a, **_k: str(tmp_path))
    started = {}
    window = MainWindow()
    monkeypatch.setattr(window._extraction_controller, "start_worker",
                        lambda **kwargs: started.update(kwargs))

    window.open_folder()
    window.start_extraction()

    assert window._pdf_label.text() == "4 PDFs: four.pdf, one.pdf, three.pdf, +1 more"
    assert [p.rsplit("/", 1)[-1] for p in started["pdf_paths"]] == [
        "four.pdf", "one.pdf", "three.pdf", "two.pdf"]
    window.close()


def test_batch_results_arrive_without_stealing_focus_and_end_with_one_summary(qapp, monkeypatch):
    warnings_shown = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda _parent, _title, text: warnings_shown.append(text))
    window = MainWindow()
    window._batch_running = True
    molecule = enrich_molecule(ExtractedMolecule(smiles="CCO", identifier="1"))

    window._on_extract_finished(ExtractionResult("first.pdf", [molecule], []))
    window._on_extract_finished(
        ExtractionResult("second.pdf", [], [], warnings=["Reactions unavailable"])
    )
    window._on_batch_pdf_failed("/papers/third.pdf", "not a PDF")
    window._on_batch_finished(2, 3)

    assert window._result_tabs.count() == 2
    assert window._result_tabs.currentIndex() == 0  # still on the first result
    assert window._detail_values["Identifier"].text() == "1"
    assert window.status_label.text() == "Extracted 2 of 3 PDFs."
    (summary,) = warnings_shown
    assert "• third.pdf: not a PDF" in summary
    assert "• second.pdf: Reactions unavailable" in summary
    window.close()
