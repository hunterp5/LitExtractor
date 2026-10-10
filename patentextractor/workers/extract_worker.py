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

"""Background thread for OpenChemIE patent extraction."""

from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal

from ..extraction_errors import ExtractionCancelled
from ..models import ExtractOptions, ExtractionResult

logger = logging.getLogger(__name__)


class ExtractWorker(QThread):
    """Run ``extract_from_pdf`` off the GUI thread."""

    progress = Signal(str)
    finished_ok = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, pdf_path: str, options: ExtractOptions, parent=None) -> None:
        super().__init__(parent)
        self._pdf_path = pdf_path
        self._options = options

    def run(self) -> None:
        try:
            from ..rdkit_env import configure_rdkit_for_desktop_app

            configure_rdkit_for_desktop_app()
            from ..extraction import extract_from_pdf

            result = extract_from_pdf(
                self._pdf_path,
                self._options,
                progress=self.progress.emit,
                should_cancel=self.isInterruptionRequested,
            )
        except ExtractionCancelled:
            logger.info("Extraction cancelled by user")
            self.cancelled.emit()
            return
        except Exception as exc:
            logger.exception("Extraction worker failed")
            self.failed.emit(str(exc))
            return
        if not isinstance(result, ExtractionResult):
            self.failed.emit("Extractor returned an unexpected result.")
            return
        self.finished_ok.emit(result)
