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

"""A zoomable window for inspecting an image (a table as printed) at full size.

It is not modal, so it can stay open beside the grid being corrected.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

MIN_ZOOM = 0.1
MAX_ZOOM = 8.0
ZOOM_STEP = 1.25


class ClickableImage(QLabel):
    """A label showing an image that reports double-clicks."""

    double_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create the label with a hint that it can be enlarged."""
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Double-click to enlarge")

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        """Report a left double-click."""
        if event.button() == Qt.LeftButton:
            self.double_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class _ImageScrollArea(QScrollArea):
    """Scroll area that zooms on Ctrl + mouse wheel instead of scrolling."""

    zoom_requested = Signal(float)

    def wheelEvent(self, event) -> None:  # noqa: N802
        """Zoom by one step per wheel notch while Ctrl (Cmd on macOS) is held."""
        if event.modifiers() & Qt.ControlModifier and event.angleDelta().y():
            self.zoom_requested.emit(ZOOM_STEP if event.angleDelta().y() > 0 else 1 / ZOOM_STEP)
            event.accept()
            return
        super().wheelEvent(event)


class ImageViewerDialog(QDialog):
    """Show one image, fitted to the window at first, with zoom controls."""

    def __init__(self, pixmap: QPixmap, title: str, parent: QWidget | None = None) -> None:
        """Open on *pixmap*, sized to most of the screen, with the image fitted to it."""
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._pixmap = pixmap
        self._zoom = 1.0

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background-color: #ffffff;")
        self.scroll_area = _ImageScrollArea()
        self.scroll_area.setAlignment(Qt.AlignCenter)
        self.scroll_area.setWidget(self.image_label)
        self.scroll_area.zoom_requested.connect(self.zoom_by)

        self.zoom_label = QLabel()
        self.zoom_label.setMinimumWidth(48)
        self.zoom_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        fit_button = QPushButton("Fit")
        fit_button.setToolTip("Fit the image to the window (Ctrl+0)")
        fit_button.clicked.connect(self.fit_to_window)
        actual_button = QPushButton("100%")
        actual_button.setToolTip("Show the image at its actual size")
        actual_button.clicked.connect(lambda: self.set_zoom(1.0))
        out_button = QPushButton("−")
        out_button.setToolTip("Zoom out (Ctrl+−, or Ctrl+scroll)")
        out_button.clicked.connect(lambda: self.zoom_by(1 / ZOOM_STEP))
        in_button = QPushButton("+")
        in_button.setToolTip("Zoom in (Ctrl+=, or Ctrl+scroll)")
        in_button.clicked.connect(lambda: self.zoom_by(ZOOM_STEP))
        size_label = QLabel(f"{pixmap.width()} × {pixmap.height()} px")

        controls = QHBoxLayout()
        controls.addWidget(size_label)
        controls.addStretch(1)
        for widget in (fit_button, actual_button, out_button, in_button, self.zoom_label):
            controls.addWidget(widget)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.scroll_area, 1)
        layout.addLayout(controls)

        for keys, slot in (
            (QKeySequence.ZoomIn, lambda: self.zoom_by(ZOOM_STEP)),
            ("Ctrl+=", lambda: self.zoom_by(ZOOM_STEP)),
            (QKeySequence.ZoomOut, lambda: self.zoom_by(1 / ZOOM_STEP)),
            ("Ctrl+0", self.fit_to_window),
        ):
            QShortcut(QKeySequence(keys), self, activated=slot)

        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry().size() if screen is not None else None
        if available is not None:
            self.resize(int(available.width() * 0.8), int(available.height() * 0.8))
        else:
            self.resize(1100, 750)
        self._fit_pending = True
        self.set_zoom(1.0)

    @property
    def zoom(self) -> float:
        """The current scale (1.0 is actual size)."""
        return self._zoom

    def set_zoom(self, zoom: float) -> None:
        """Show the image at *zoom* times its size (clamped to a sensible range)."""
        self._zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        width = max(1, round(self._pixmap.width() * self._zoom))
        self.image_label.setPixmap(
            self._pixmap.scaledToWidth(width, Qt.SmoothTransformation)
        )
        self.image_label.resize(self.image_label.pixmap().size())
        self.zoom_label.setText(f"{round(self._zoom * 100)}%")

    def zoom_by(self, factor: float) -> None:
        """Zoom in (factor > 1) or out (factor < 1)."""
        self._fit_pending = False
        self.set_zoom(self._zoom * factor)

    def fit_zoom(self) -> float:
        """The zoom at which the whole image fits the visible area, at most 4×."""
        viewport = self.scroll_area.viewport().size()
        if self._pixmap.isNull() or viewport.width() <= 0 or viewport.height() <= 0:
            return 1.0
        return min(viewport.width() / self._pixmap.width(),
                   viewport.height() / self._pixmap.height(), 4.0)

    def fit_to_window(self) -> None:
        """Fit the whole image to the window."""
        self._fit_pending = False
        self.set_zoom(self.fit_zoom())

    def showEvent(self, event) -> None:  # noqa: N802
        """Fit the image once the window has its real size."""
        super().showEvent(event)
        if self._fit_pending:
            self.fit_to_window()
