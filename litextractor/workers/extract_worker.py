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

"""Background thread for OpenChemIE extraction of one PDF or a batch."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..extraction_errors import ExtractionCancelled
from ..models import ExtractOptions

logger = logging.getLogger(__name__)


class ExtractWorker(QThread):
    """Run ``extract_from_pdf`` off the GUI thread, for one PDF or several in turn.

    Each finished PDF is reported with ``finished_ok`` as soon as it is done. With one PDF a
    failure is reported with ``failed``; with several, a failed PDF is reported with
    ``pdf_failed`` and the next one starts, and ``batch_finished`` follows the last.
    """

    progress = Signal(str)
    finished_ok = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    #: One PDF of a batch failed: its path and the error message.
    pdf_failed = Signal(str, str)
    #: A batch ended (not cancelled): how many PDFs were extracted, and how many there were.
    batch_finished = Signal(int, int)

    def __init__(
        self, pdf_paths: str | list[str], options: ExtractOptions, parent=None
    ) -> None:
        """Remember the PDF(s) and extraction options; the work starts when the thread runs."""
        super().__init__(parent)
        self._pdf_paths = [pdf_paths] if isinstance(pdf_paths, str) else list(pdf_paths)
        self._options = options

    @property
    def is_batch(self) -> bool:
        """True when several PDFs are extracted."""
        return len(self._pdf_paths) > 1

    def run(self) -> None:
        """Extract each PDF on the worker thread, emitting the outcome signals as it goes."""
        try:
            from ..extraction import extract_from_pdf
        except Exception as exc:
            logger.exception("Could not load the extraction pipeline")
            self.failed.emit(str(exc))
            return

        total = len(self._pdf_paths)
        extracted = 0
        for number, pdf_path in enumerate(self._pdf_paths, start=1):
            if self.isInterruptionRequested():
                self.cancelled.emit()
                return
            prefix = f"[{number}/{total}] {Path(pdf_path).name}: " if self.is_batch else ""
            try:
                result = extract_from_pdf(
                    pdf_path,
                    self._options,
                    progress=lambda message, prefix=prefix: self.progress.emit(prefix + message),
                    should_cancel=self.isInterruptionRequested,
                )
            except ExtractionCancelled:
                logger.info("Extraction cancelled by user")
                self.cancelled.emit()
                return
            except Exception as exc:
                logger.exception("Extraction of %s failed", pdf_path)
                if not self.is_batch:
                    self.failed.emit(str(exc))
                    return
                self.pdf_failed.emit(pdf_path, str(exc))
                continue
            extracted += 1
            self.finished_ok.emit(result)
        if self.is_batch:
            self.batch_finished.emit(extracted, total)
