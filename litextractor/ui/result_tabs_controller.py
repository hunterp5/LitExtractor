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

"""Controller for multi-run extraction result tabs."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QMenu, QMessageBox, QStackedWidget, QTabWidget, QWidget

from ..models import ExtractionResult
from .startup_page import StartupPage

if TYPE_CHECKING:
    from .extraction_result_tab import ExtractionResultTab


class ResultTabsController:
    """Own result-tab lifecycle and active-tab synchronization."""

    def __init__(
        self,
        *,
        parent: QWidget,
        app_name: str,
        result_tabs: QTabWidget,
        results_stack: QStackedWidget,
        startup_page: StartupPage,
        on_molecule_selected: Callable[..., None],
    ) -> None:
        self._parent = parent
        self._app_name = app_name
        self._result_tabs = result_tabs
        self._results_stack = results_stack
        self._startup_page = startup_page
        self._on_molecule_selected = on_molecule_selected

    def result_tab_widgets(self) -> list[ExtractionResultTab]:
        """Return every extraction tab widget currently hosted."""
        if self._result_tabs.count() == 0:
            return []
        from .extraction_result_tab import ExtractionResultTab

        return [
            widget
            for index in range(self._result_tabs.count())
            if isinstance(widget := self._result_tabs.widget(index), ExtractionResultTab)
        ]

    def add_result(self, result: ExtractionResult, *, table_font_pt: int) -> ExtractionResultTab:
        """Create and activate a new result tab for one extraction run."""
        # Imported lazily so application startup does not load RDKit.
        from .extraction_result_tab import ExtractionResultTab

        result_tab = ExtractionResultTab(self._result_tabs)
        result_tab.set_result(result)
        result_tab.apply_table_font(table_font_pt)
        result_tab.apply_structure_layout()
        result_tab.molecule_table.selectionModel().selectionChanged.connect(
            self._on_molecule_selected
        )
        self._result_tabs.addTab(result_tab, Path(result.pdf_path).name)
        self._result_tabs.setCurrentWidget(result_tab)
        self._results_stack.setCurrentWidget(self._result_tabs)
        self._startup_page.set_loading(False)
        return result_tab

    def active_result_tab(self, index: int | None) -> ExtractionResultTab | None:
        """Resolve the currently active extraction tab by index."""
        if index is None or not 0 <= index < self._result_tabs.count():
            return None
        # Imported lazily so application startup does not load RDKit.
        from .extraction_result_tab import ExtractionResultTab

        result_tab = self._result_tabs.widget(index)
        if not isinstance(result_tab, ExtractionResultTab):
            return None
        return result_tab

    def show_context_menu(
        self,
        position: QPoint,
        *,
        menu_factory: Callable[[QWidget], QMenu] = QMenu,
    ) -> int | None:
        """Open the result-tab context menu and return a selected delete index."""
        index = self._result_tabs.tabBar().tabAt(position)
        if index < 0:
            return None
        menu = menu_factory(self._parent)
        close_action = menu.addAction("Close tab")
        if menu.exec(self._result_tabs.tabBar().mapToGlobal(position)) is close_action:
            return index
        return None

    def confirm_delete(self, index: int) -> bool:
        """Ask the user and delete a result tab when confirmed."""
        if not 0 <= index < self._result_tabs.count():
            return False
        name = self._result_tabs.tabText(index)
        answer = QMessageBox.question(
            self._parent,
            self._app_name,
            f"Delete '{name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return False
        result_tab = self._result_tabs.widget(index)
        self._result_tabs.removeTab(index)
        if result_tab is not None:
            result_tab.deleteLater()
        if self._result_tabs.count() == 0:
            self._results_stack.setCurrentWidget(self._startup_page)
        return True

    def set_startup_view(self) -> None:
        """Switch the center panel back to the startup page."""
        self._results_stack.setCurrentWidget(self._startup_page)
