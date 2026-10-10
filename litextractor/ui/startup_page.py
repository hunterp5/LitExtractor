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

"""Minimal idle and first-extraction status view for the main workspace."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class StartupPage(QFrame):
    """Centered status message shown before results are available."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the centered, word-wrapped message label shown in the idle state."""
        super().__init__(parent)
        self.setObjectName("WelcomePage")
        self.setAutoFillBackground(True)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        outer_layout.addStretch(1)
        self.message_label = QLabel(
            "Open a patent PDF to begin.\nMolecule and reaction results will appear here.",
            self,
        )
        self.message_label.setObjectName("WorkspaceStatus")
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setWordWrap(True)
        outer_layout.addWidget(self.message_label)
        outer_layout.addStretch(1)

    def set_loading(self, loading: bool, message: str | None = None) -> None:
        """Update the centered idle or extraction-progress message."""
        if loading:
            self.message_label.setText(message or "Preparing the extraction pipeline…")
        else:
            self.message_label.setText(
                message
                or "Open a patent PDF to begin.\nMolecule and reaction results will appear here."
            )
