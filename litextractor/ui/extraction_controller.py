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

"""Controller for extraction-worker lifecycle and busy-state updates."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QLabel, QMessageBox, QProgressBar, QPushButton, QStackedWidget, QTabWidget, QWidget

from ..models import ExtractOptions
from .startup_page import StartupPage


class ExtractionController:
    """Coordinate worker startup/cancellation while keeping MainWindow slim."""

    def __init__(
        self,
        *,
        parent: QWidget,
        app_name: str,
        extract_button: QPushButton,
        cancel_button: QPushButton,
        progress_bar: QProgressBar,
        extract_status: QLabel,
        status_label: QLabel,
        result_tabs: QTabWidget,
        startup_page: StartupPage,
        results_stack: QStackedWidget,
        get_worker: Callable[[], object | None],
        set_worker: Callable[[object | None], None],
        get_close_after_worker: Callable[[], bool],
        set_close_after_worker: Callable[[bool], None],
    ) -> None:
        self._parent = parent
        self._app_name = app_name
        self._extract_button = extract_button
        self._cancel_button = cancel_button
        self._progress_bar = progress_bar
        self._extract_status = extract_status
        self._status_label = status_label
        self._result_tabs = result_tabs
        self._startup_page = startup_page
        self._results_stack = results_stack
        self._get_worker = get_worker
        self._set_worker = set_worker
        self._get_close_after_worker = get_close_after_worker
        self._set_close_after_worker = set_close_after_worker

    def set_busy(self, busy: bool) -> None:
        """Update extraction-control widgets for running vs idle states."""
        self._extract_button.setEnabled(not busy)
        self._cancel_button.setEnabled(busy)
        self._progress_bar.setVisible(busy)

    def start_worker(
        self,
        *,
        pdf_path: str,
        options: ExtractOptions,
        on_progress: Callable[[str], None],
        on_finished: Callable[[object], None],
        on_failed: Callable[[str], None],
        on_cancelled: Callable[[], None],
        on_thread_finished: Callable[[], None],
    ) -> None:
        """Create and start an extraction worker thread."""
        from ..workers.extract_worker import ExtractWorker

        self.set_busy(True)
        self._extract_status.setText("Starting…")
        worker = ExtractWorker(pdf_path, options, self._parent)
        self._set_worker(worker)
        worker.progress.connect(on_progress)
        worker.finished_ok.connect(on_finished)
        worker.failed.connect(on_failed)
        worker.cancelled.connect(on_cancelled)
        worker.finished.connect(on_thread_finished)
        worker.start()

    def cancel_worker(self) -> None:
        """Request cooperative cancellation for the active extraction worker."""
        worker = self._get_worker()
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            self._extract_status.setText("Cancel requested — waiting for the current step…")
            self._status_label.setText("Cancel requested.")

    def handle_close_event(self, event: QCloseEvent) -> bool:
        """Request cancellation and defer close while a worker is still running."""
        worker = self._get_worker()
        if worker is None or not worker.isRunning():
            return False
        self._set_close_after_worker(True)
        self.cancel_worker()
        event.ignore()
        return True

    def handle_worker_thread_finished(self) -> None:
        """Restore idle state and close the window if a deferred close was requested."""
        self.set_busy(False)
        self._set_worker(None)
        if self._get_close_after_worker():
            self._set_close_after_worker(False)
            self._parent.close()

    def handle_progress(self, message: str) -> None:
        """Update startup and status views for extraction progress."""
        self._extract_status.setText(message)
        self._status_label.setText(message)
        if self._result_tabs.count() == 0:
            self._startup_page.set_loading(True, message)
            self._results_stack.setCurrentWidget(self._startup_page)

    def handle_failed(self, message: str) -> None:
        """Show a fatal extraction error and keep startup state consistent."""
        self._extract_status.setText(message)
        self._status_label.setText("Extraction failed.")
        if self._result_tabs.count() == 0:
            self._startup_page.set_loading(False, message)
            self._results_stack.setCurrentWidget(self._startup_page)
        QMessageBox.critical(self._parent, self._app_name, message)

    def handle_cancelled(self) -> None:
        """Reflect user-cancelled extraction in the startup and status widgets."""
        self._extract_status.setText("Extraction cancelled.")
        self._status_label.setText("Extraction cancelled.")
        if self._result_tabs.count() == 0:
            self._startup_page.set_loading(False)
            self._results_stack.setCurrentWidget(self._startup_page)
