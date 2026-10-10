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

"""Main window: extract panel, results table, detail pane, MolManager-matching themes."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..crop_context import DEFAULT_MOLECULE_CROP_MARGIN
from ..structure_layout import (
    DETAIL_STRUCTURE_HEIGHT,
    DETAIL_STRUCTURE_WIDTH,
    load_saved_structure_size,
    set_structure_size,
    structure_height,
    structure_width,
)
from ..chemistry import molecule_quality_score, parse_mol
from ..extraction import cuda_available
from ..export import write_csv, write_sdf, write_smi
from ..models import ExtractOptions, ExtractedMolecule, ExtractionResult
from ..structure_draw import render_molecule_png
from ..workers.extract_worker import ExtractWorker
from .dialogs.citations import CitationsDialog
from .dialogs.font_settings import FontSettingsDialog
from .dialogs.structure_settings import StructureSettingsDialog
from .extraction_result_tab import ExtractionResultTab
from .molecule_table import pixmap_from_png
from .startup_page import StartupPage
from .theme import (
    THEME_DARK,
    THEME_GROOVY,
    THEME_LIGHT,
    apply_application_font_pt,
    apply_application_theme,
    current_theme_name,
    default_app_font_pt,
    default_table_font_pt,
    detail_panel_stylesheet,
    extract_panel_stylesheet,
    load_saved_app_font_pt,
    load_saved_table_font_pt,
    load_saved_theme_name,
    save_app_font_pt,
    save_table_font_pt,
    save_theme_name,
)

logger = logging.getLogger(__name__)

APP_NAME = "PatentExtractor"
_SETTINGS_ORG = "PatentExtractor"
_SETTINGS_APP = "PatentExtractor"
_SETTINGS_KEY_LAST_DIR = "files/last_dir"

_EXTRACT_PANEL_WIDTH = 280
_DETAIL_PANEL_WIDTH = 420


class MainWindow(QMainWindow):
    """Patent extraction workspace with MolManager Fusion themes."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1400, 820)
        self._pdf_path: str | None = None
        self._result: ExtractionResult | None = None
        self._active_result_tab: ExtractionResultTab | None = None
        self._worker: ExtractWorker | None = None
        self._close_after_worker = False
        self._app_font_pt = load_saved_app_font_pt()
        apply_application_font_pt(self._app_font_pt)
        self._gui_theme = load_saved_theme_name()
        self._table_font_pt = load_saved_table_font_pt()
        w, h = load_saved_structure_size()
        set_structure_size(w, h, persist=False)

        self._build_menus()
        self._build_central()
        apply_application_theme(QApplication.instance(), self._gui_theme)
        self._empty_result_tab = ExtractionResultTab(self)
        self._empty_result_tab.hide()
        self._set_active_result_tab(None)
        self.status_label = getattr(self, "_extract_status", QLabel("Ready — open a patent PDF to extract structures."))
        self.statusBar().hide()
        self._apply_table_font()
        self.refresh_theme()

    def _settings(self) -> QSettings:
        return QSettings(_SETTINGS_ORG, _SETTINGS_APP)

    def _last_dir(self) -> str:
        raw = str(self._settings().value(_SETTINGS_KEY_LAST_DIR) or "")
        return raw if raw and Path(raw).is_dir() else str(Path.home())

    def _set_last_dir(self, path: str) -> None:
        parent = str(Path(path).parent)
        self._settings().setValue(_SETTINGS_KEY_LAST_DIR, parent)

    def _build_menus(self) -> None:
        menubar = self.menuBar()
        self._file_menu = menubar.addMenu("&File")
        file_menu = self._file_menu
        file_menu.addAction(QAction("&Open PDF…", self, shortcut="Ctrl+O", triggered=self.open_pdf))
        file_menu.addSeparator()
        file_menu.addAction(QAction("Export &CSV…", self, triggered=self.export_csv))
        file_menu.addAction(QAction("Export S&DF…", self, triggered=self.export_sdf))
        file_menu.addAction(QAction("Export S&MILES…", self, triggered=self.export_smi))
        file_menu.addSeparator()
        file_menu.addAction(QAction("E&xit", self, shortcut="Ctrl+Q", triggered=self.close))

        self._settings_menu = menubar.addMenu("&Settings")
        settings_menu = self._settings_menu
        self._gui_menu = settings_menu.addMenu("&GUI")
        self._act_theme_light = QAction("Light Mode", self, checkable=True)
        self._act_theme_dark = QAction("Dark Mode", self, checkable=True)
        self._act_theme_groovy = QAction("Groovy Mode", self, checkable=True)
        self._theme_action_group = QActionGroup(self)
        self._theme_action_group.setExclusive(True)
        self._theme_action_group.addAction(self._act_theme_light)
        self._theme_action_group.addAction(self._act_theme_dark)
        self._theme_action_group.addAction(self._act_theme_groovy)
        self._act_theme_light.triggered.connect(lambda: self._set_gui_theme(THEME_LIGHT))
        self._act_theme_dark.triggered.connect(lambda: self._set_gui_theme(THEME_DARK))
        self._act_theme_groovy.triggered.connect(lambda: self._set_gui_theme(THEME_GROOVY))
        self._gui_menu.addAction(self._act_theme_light)
        self._gui_menu.addAction(self._act_theme_dark)
        self._gui_menu.addAction(self._act_theme_groovy)
        self._sync_theme_menu_checks()
        settings_menu.addSeparator()
        settings_menu.addAction(
            QAction("&Structure…", self, triggered=self.open_structure_settings)
        )
        settings_menu.addAction(QAction("&Font…", self, triggered=self.open_font_dialog))

        self._help_menu = menubar.addMenu("&Help")
        help_menu = self._help_menu
        help_menu.addAction(QAction("&User Guide", self, triggered=self.show_user_guide))
        help_menu.addAction(QAction("&Citations", self, triggered=self.show_citations))

    def _sync_theme_menu_checks(self) -> None:
        name = getattr(self, "_gui_theme", current_theme_name()) or current_theme_name()
        self._act_theme_light.setChecked(name == THEME_LIGHT)
        self._act_theme_dark.setChecked(name == THEME_DARK)
        self._act_theme_groovy.setChecked(name == THEME_GROOVY)

    def _build_central(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        extract_panel = self._build_extract_panel()
        extract_panel.setFixedWidth(_EXTRACT_PANEL_WIDTH)
        layout.addWidget(extract_panel)

        layout.addWidget(self._build_results_tabs(), 1)
        detail_panel = self._build_detail_panel()
        detail_panel.setFixedWidth(_DETAIL_PANEL_WIDTH)
        layout.addWidget(detail_panel)
        self.setCentralWidget(central)

    def _build_extract_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("ExtractPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        source_group = QGroupBox("PDF")
        source_layout = QVBoxLayout(source_group)
        self._pdf_label = QLabel("No PDF selected")
        self._pdf_label.setWordWrap(True)
        open_btn = QPushButton("Open PDF…")
        open_btn.clicked.connect(self.open_pdf)
        source_layout.addWidget(self._pdf_label)
        source_layout.addWidget(open_btn)
        layout.addWidget(source_group)

        content_group = QGroupBox("Extract")
        content_layout = QVBoxLayout(content_group)
        self._chk_figures = QCheckBox("Molecules from figures")
        self._chk_figures.setChecked(True)
        self._chk_text = QCheckBox("Names from Text")
        self._chk_text.setChecked(True)
        self._chk_corefs = QCheckBox("Figure–label coreferences")
        self._chk_corefs.setChecked(True)
        self._chk_reactions = QCheckBox("Reactions")
        self._chk_reactions.setChecked(False)
        self._chk_merge = QCheckBox("Merge duplicates (InChIKey)")
        self._chk_merge.setChecked(True)
        content_layout.addWidget(self._chk_figures)
        content_layout.addWidget(self._chk_text)
        content_layout.addWidget(self._chk_corefs)
        content_layout.addWidget(self._chk_reactions)
        content_layout.addWidget(self._chk_merge)
        layout.addWidget(content_group)

        page_group = QGroupBox("Page range")
        page_layout = QVBoxLayout(page_group)
        self._all_pages_chk = QCheckBox("All Pages")
        self._all_pages_chk.setChecked(True)
        self._all_pages_chk.setToolTip("Process the full PDF from the first page onward.")
        page_layout.addWidget(self._all_pages_chk)
        page_form = QFormLayout()
        page_form.setSpacing(4)
        self._first_page_spin = QSpinBox()
        self._first_page_spin.setRange(1, 9999)
        self._first_page_spin.setValue(1)
        self._first_page_spin.setToolTip("1-based page to start on.")
        page_form.addRow("First page:", self._first_page_spin)

        self._pages_spin = QSpinBox()
        self._pages_spin.setRange(0, 9999)
        self._pages_spin.setValue(5)
        self._pages_spin.setSpecialValueText("All")
        self._pages_spin.setToolTip(
            "How many pages to process from First page. 0 = through the end."
        )
        page_form.addRow("Page count:", self._pages_spin)
        page_layout.addLayout(page_form)
        layout.addWidget(page_group)

        structure_group = QGroupBox("Structure limit")
        structure_layout = QVBoxLayout(structure_group)
        self._all_structures_chk = QCheckBox("All Structures")
        self._all_structures_chk.setChecked(True)
        self._all_structures_chk.setToolTip("Ignore the structure cap and extract all detected molecules.")
        structure_layout.addWidget(self._all_structures_chk)
        structure_form = QFormLayout()
        structure_form.setSpacing(4)
        self._max_mols_spin = QSpinBox()
        self._max_mols_spin.setRange(0, 99999)
        self._max_mols_spin.setValue(50)
        self._max_mols_spin.setSpecialValueText("All")
        self._max_mols_spin.setToolTip("Stop after this many structures. 0 = no cap.")
        structure_form.addRow("Max structures:", self._max_mols_spin)
        structure_layout.addLayout(structure_form)
        layout.addWidget(structure_group)

        processing_group = QGroupBox("Processing")
        processing_form = QFormLayout(processing_group)
        processing_form.setSpacing(4)

        self._device_combo = QComboBox()
        self._device_combo.setToolTip(
            "CUDA appears only when a compatible NVIDIA GPU and drivers are available, "
            "otherwise CPU is used."
        )
        self._device_combo.addItem("CPU", "cpu")
        if self._cuda_available():
            self._device_combo.addItem("CUDA (GPU)", "cuda")
            self._device_combo.setCurrentIndex(self._device_combo.findData("cuda"))
        processing_form.addRow("Device:", self._device_combo)

        self._crop_margin_spin = QDoubleSpinBox()
        self._crop_margin_spin.setRange(0.0, 50.0)
        self._crop_margin_spin.setDecimals(1)
        self._crop_margin_spin.setSingleStep(1.0)
        self._crop_margin_spin.setSuffix("%")
        self._crop_margin_spin.setValue(DEFAULT_MOLECULE_CROP_MARGIN * 100.0)
        self._crop_margin_spin.setToolTip(
            "Expand each detection box by this percentage in every direction before cropping."
        )
        processing_form.addRow("Crop expansion:", self._crop_margin_spin)
        layout.addWidget(processing_group)

        btn_row = QHBoxLayout()
        self._extract_btn = QPushButton("Extract")
        self._extract_btn.setDefault(True)
        self._extract_btn.clicked.connect(self.start_extraction)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self.cancel_extraction)
        btn_row.addWidget(self._extract_btn)
        btn_row.addWidget(self._cancel_btn)
        layout.addLayout(btn_row)

        self._sync_all_pages_state()
        self._sync_all_structures_state()
        self._all_pages_chk.toggled.connect(self._sync_all_pages_state)
        self._all_structures_chk.toggled.connect(self._sync_all_structures_state)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._extract_status = QLabel("")
        self._extract_status.setWordWrap(True)
        layout.addWidget(self._extract_status)
        layout.addStretch(1)
        self._extract_panel = panel
        return panel

    def _build_results_tabs(self) -> QStackedWidget:
        self._startup_page = StartupPage()
        self._result_tabs = QTabWidget()
        self._result_tabs.currentChanged.connect(self._on_result_tab_changed)
        tab_bar = self._result_tabs.tabBar()
        tab_bar.setContextMenuPolicy(Qt.CustomContextMenu)
        tab_bar.customContextMenuRequested.connect(self._show_result_tab_context_menu)

        self._results_stack = QStackedWidget()
        self._results_stack.addWidget(self._startup_page)
        self._results_stack.addWidget(self._result_tabs)
        self._results_stack.setCurrentWidget(self._startup_page)
        # Keep the historic central-results attribute pointing at the stack.
        self._tabs = self._results_stack
        return self._results_stack

    def _build_detail_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("DetailPanel")
        panel.setMinimumWidth(280)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)

        structure_card = QFrame()
        structure_card.setObjectName("DetailCard")
        structure_layout = QVBoxLayout(structure_card)
        structure_layout.setContentsMargins(10, 8, 10, 10)
        structure_layout.setSpacing(6)
        structure_title = QLabel("Chemical structure")
        structure_title.setObjectName("DetailCardTitle")
        structure_layout.addWidget(structure_title)
        self._detail_structure = QLabel()
        self._detail_structure.setAlignment(Qt.AlignCenter)
        self._detail_structure.setMinimumHeight(DETAIL_STRUCTURE_HEIGHT)
        self._detail_structure.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._detail_structure.setText("Select a molecule")
        structure_layout.addWidget(self._detail_structure)
        content_layout.addWidget(structure_card)

        self._detail_crop_card = QFrame()
        self._detail_crop_card.setObjectName("DetailCard")
        crop_layout = QVBoxLayout(self._detail_crop_card)
        crop_layout.setContentsMargins(10, 8, 10, 10)
        crop_layout.setSpacing(6)
        crop_title = QLabel("Patent crop")
        crop_title.setObjectName("DetailCardTitle")
        crop_layout.addWidget(crop_title)
        self._detail_crop = QLabel("—")
        self._detail_crop.setObjectName("CropPreview")
        self._detail_crop.setAlignment(Qt.AlignCenter)
        self._detail_crop.setMinimumHeight(120)
        crop_layout.addWidget(self._detail_crop)
        content_layout.addWidget(self._detail_crop_card)

        details_card = QFrame()
        details_card.setObjectName("DetailCard")
        details_layout = QVBoxLayout(details_card)
        details_layout.setContentsMargins(10, 8, 10, 10)
        details_layout.setSpacing(6)
        details_title = QLabel("Molecule information")
        details_title.setObjectName("DetailCardTitle")
        details_layout.addWidget(details_title)
        fields_layout = QGridLayout()
        fields_layout.setHorizontalSpacing(12)
        fields_layout.setVerticalSpacing(5)
        self._detail_values: dict[str, QLabel] = {}
        field_names = (
            "Identifier",
            "Page",
            "Source",
            "Quality",
            "Formula",
            "Molecular weight",
            "InChIKey",
        )
        for row, name in enumerate(field_names):
            field_label = QLabel(name)
            field_label.setObjectName("DetailFieldName")
            value = QLabel("—")
            value.setObjectName("DetailFieldValue")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._detail_values[name] = value
            fields_layout.addWidget(field_label, row, 0, Qt.AlignTop)
            fields_layout.addWidget(value, row, 1)
        fields_layout.setColumnStretch(1, 1)
        details_layout.addLayout(fields_layout)
        content_layout.addWidget(details_card)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        self._detail_panel = panel
        self._clear_detail()
        panel.hide()
        return panel

    def refresh_theme(self) -> None:
        """Refresh palette-driven component styling after an application theme change."""
        if not hasattr(self, "_result_tabs"):
            return
        extract = getattr(self, "_extract_panel", None)
        if extract is not None:
            extract.setStyleSheet(extract_panel_stylesheet())
        detail = getattr(self, "_detail_panel", None)
        if detail is not None:
            detail.setStyleSheet(detail_panel_stylesheet())
        for result_tab in self._result_tab_widgets():
            result_tab.refresh_theme()
        empty_tab = getattr(self, "_empty_result_tab", None)
        if empty_tab is not None:
            empty_tab.refresh_theme()
        if getattr(self, "_table_font_pt", None) is not None:
            self._apply_table_font()
        self.update()

    def _set_gui_theme(self, theme: str) -> None:
        app = QApplication.instance()
        theme = apply_application_theme(app, theme)
        self._gui_theme = theme
        save_theme_name(theme)
        self._sync_theme_menu_checks()
        apply_application_font_pt(int(self._app_font_pt or default_app_font_pt()))

    def open_structure_settings(self) -> None:
        prev_w, prev_h = structure_width(), structure_height()
        dlg = StructureSettingsDialog(prev_w, prev_h, self)
        dlg.size_previewed.connect(
            lambda w, h: self.apply_structure_size(w, h, persist=False)
        )
        if dlg.exec() == QDialog.Accepted:
            self.apply_structure_size(
                dlg.selected_width(), dlg.selected_height(), persist=True
            )
        else:
            self.apply_structure_size(prev_w, prev_h, persist=False)
        self.status_label.setText(
            f"Structure image size — {structure_width()}×{structure_height()} px"
        )

    def apply_structure_size(
        self, width: int, height: int, *, persist: bool = True
    ) -> None:
        set_structure_size(width, height, persist=persist)
        for result_tab in self._result_tab_widgets():
            result_tab.apply_structure_layout()
            result_tab.rerender_structures()
        self._empty_result_tab.apply_structure_layout()
        self._empty_result_tab.rerender_structures()
        self._refresh_selected_detail()

    def open_font_dialog(self) -> None:
        prev_app = int(self._app_font_pt or default_app_font_pt())
        prev_table = int(self._table_font_pt or default_table_font_pt())
        dlg = FontSettingsDialog(prev_app, prev_table, self)
        dlg.app_font_size_previewed.connect(self._preview_app_font)
        dlg.table_font_size_previewed.connect(self._preview_table_font)
        if dlg.exec() == QDialog.Accepted:
            self._set_app_font_pt(dlg.selected_app_point_size())
            self._set_table_font_pt(dlg.selected_table_point_size())
        else:
            self._set_app_font_pt(prev_app, persist=False)
            self._set_table_font_pt(prev_table, persist=False)
        self.status_label.setText(
            f"Font size — application: {self._app_font_pt} pt, table: {self._table_font_pt} pt"
        )

    def _preview_app_font(self, pt: int) -> None:
        self._set_app_font_pt(pt, persist=False)

    def _preview_table_font(self, pt: int) -> None:
        self._set_table_font_pt(pt, persist=False)

    def _set_app_font_pt(self, pt: int, *, persist: bool = True) -> None:
        self._app_font_pt = apply_application_font_pt(pt)
        if persist:
            save_app_font_pt(self._app_font_pt)

    def _set_table_font_pt(self, pt: int, *, persist: bool = True) -> None:
        self._table_font_pt = int(pt)
        self._apply_table_font()
        if persist:
            save_table_font_pt(self._table_font_pt)

    def _apply_table_font(self) -> None:
        for result_tab in self._result_tab_widgets():
            result_tab.apply_table_font(self._table_font_pt)
        empty_tab = getattr(self, "_empty_result_tab", None)
        if empty_tab is not None:
            empty_tab.apply_table_font(self._table_font_pt)

    def show_user_guide(self) -> None:
        QMessageBox.information(
            self,
            f"{APP_NAME} User Guide",
            "<h3>PatentExtractor User Guide</h3>"
            "<p><b>1. Open a PDF</b><br>"
            "Use <b>File → Open PDF…</b> to load a patent or chemistry PDF. The app "
            "keeps track of your last folder so you can navigate quickly.</p>"
            "<p><b>2. Choose extraction sources</b><br>"
            "In the Extract panel, select which data sources to use: figures, text, "
            "coreferences, and/or reactions. More sources improve coverage but may take "
            "longer.</p>"
            "<p><b>3. Pick the page range and device</b><br>"
            "Set the first page and page count to process a subset of the PDF. Choose "
            "<b>CPU</b> or <b>CUDA (GPU)</b> when a compatible GPU is available. GPU is "
            "significantly faster for large jobs.</p>"
            "<p><b>4. Extract molecules</b><br>"
            "Click <b>Extract</b> to run the OpenChemIE pipeline. The first extraction may "
            "download model weights and take longer. The status bar shows progress and any "
            "warnings while extraction is running.</p>"
            "<p><b>5. Review results</b><br>"
            "The main results tabs list molecules and reactions. Select a row to inspect the "
            "matching chemical structure, identifiers, source metadata, and extracted details "
            "in the detail pane.</p>"
            "<p><b>6. Merge and clean results</b><br>"
            "Use the merge option to combine duplicates by InChIKey. This helps when the same "
            "molecule appears multiple times across pages or figure regions.</p>"
            "<p><b>7. Export data</b><br>"
            "Use <b>File → Export CSV…</b>, <b>Export SDF…</b>, or <b>Export SMILES…</b> "
            "to save the extracted structures and metadata in a format suitable for further "
            "analysis or workflow integration.</p>"
            "<p><b>8. Customize the interface</b><br>"
            "Open <b>Settings → GUI</b> to switch between Light, Dark, and Groovy themes. "
            "Your choice is remembered when you reopen the app. Structure rendering and font "
            "settings are also available under Settings.</p>"
            "<p><b>Tips</b><br>"
            "- Install Poppler for PDF rendering support.<br>"
            "- On Python 3.10/3.11, OpenChemIE may require a manual torch 2.x workaround "
            "before installing from its Git repo.<br>"
            "- If the Extract panel warns that OpenChemIE is unavailable, install the "
            "project requirements again in the active venv.</p>",
        )

    def show_citations(self) -> None:
        """Open the citation guide for the application and its core technology stack."""
        CitationsDialog(self).exec()

    def open_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open patent PDF",
            self._last_dir(),
            "PDF files (*.pdf);;All files (*.*)",
        )
        if not path:
            return
        self._set_pdf_path(path)

    def _set_pdf_path(self, path: str) -> None:
        self._pdf_path = path
        self._set_last_dir(path)
        self._pdf_label.setText(Path(path).name)
        self._pdf_label.setToolTip(path)
        self.status_label.setText(f"Opened {Path(path).name}")

    def _sync_all_pages_state(self) -> None:
        enabled = not self._all_pages_chk.isChecked()
        self._first_page_spin.setEnabled(enabled)
        self._pages_spin.setEnabled(enabled)

    def _sync_all_structures_state(self) -> None:
        self._max_mols_spin.setEnabled(not self._all_structures_chk.isChecked())

    @staticmethod
    def _cuda_available() -> bool:
        return cuda_available()

    def _current_options(self) -> ExtractOptions:
        max_mols = int(self._max_mols_spin.value())
        first_page = int(self._first_page_spin.value())
        page_count = int(self._pages_spin.value())
        if self._all_pages_chk.isChecked():
            first_page = 1
            page_count = 0
        if self._all_structures_chk.isChecked():
            max_mols = 0
        return ExtractOptions(
            figures=self._chk_figures.isChecked(),
            text=self._chk_text.isChecked(),
            corefs=self._chk_corefs.isChecked(),
            reactions=self._chk_reactions.isChecked(),
            merge_by_inchi=self._chk_merge.isChecked(),
            first_page=first_page,
            num_pages=page_count if page_count > 0 else None,
            max_molecules=max_mols if max_mols > 0 else None,
            device=str(self._device_combo.currentData() or "cpu"),
            crop_margin=max(0.0, float(self._crop_margin_spin.value()) / 100.0),
        )

    def start_extraction(self) -> None:
        if not self._pdf_path:
            self.open_pdf()
            if not self._pdf_path:
                return
        opts = self._current_options()
        if not (opts.figures or opts.text or opts.reactions or opts.corefs):
            QMessageBox.information(self, APP_NAME, "Select at least one extraction source.")
            return
        self._set_busy(True)
        self._extract_status.setText("Starting…")
        self._worker = ExtractWorker(self._pdf_path, opts, self)
        self._worker.progress.connect(self._on_extract_progress)
        self._worker.finished_ok.connect(self._on_extract_finished)
        self._worker.failed.connect(self._on_extract_failed)
        self._worker.cancelled.connect(self._on_extract_cancelled)
        self._worker.finished.connect(self._on_worker_thread_finished)
        self._worker.start()

    def cancel_extraction(self) -> None:
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            self._extract_status.setText("Cancel requested — waiting for the current step…")
            self.status_label.setText("Cancel requested.")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        worker = self._worker
        if worker is not None and worker.isRunning():
            self._close_after_worker = True
            self.cancel_extraction()
            event.ignore()
            return
        super().closeEvent(event)

    def _on_worker_thread_finished(self) -> None:
        self._set_busy(False)
        if self._close_after_worker:
            self._close_after_worker = False
            self.close()

    def _set_busy(self, busy: bool) -> None:
        self._extract_btn.setEnabled(not busy)
        self._cancel_btn.setEnabled(busy)
        self._progress.setVisible(busy)

    def _on_extract_progress(self, message: str) -> None:
        self._extract_status.setText(message)
        self.status_label.setText(message)
        if self._result_tabs.count() == 0:
            self._startup_page.set_loading(True, message)
            self._results_stack.setCurrentWidget(self._startup_page)

    def _on_extract_finished(self, result: object) -> None:
        if not isinstance(result, ExtractionResult):
            self._on_extract_failed("Unexpected extraction result.")
            return
        result_tab = ExtractionResultTab(self._result_tabs)
        result_tab.set_result(result)
        result_tab.apply_table_font(self._table_font_pt)
        result_tab.apply_structure_layout()
        result_tab.molecule_table.selectionModel().selectionChanged.connect(
            self._on_molecule_selected
        )
        self._result_tabs.addTab(result_tab, Path(result.pdf_path).name)
        self._result_tabs.setCurrentWidget(result_tab)
        self._results_stack.setCurrentWidget(self._result_tabs)
        self._detail_panel.show()
        if result.molecules:
            result_tab.molecule_table.selectRow(0)
        else:
            self._clear_detail()
        self._startup_page.set_loading(False)
        warn = ""
        if result.warnings:
            warn = " Warnings: " + "; ".join(result.warnings)
            QMessageBox.warning(self, APP_NAME, "\n".join(result.warnings))
        self.status_label.setText(
            f"{Path(result.pdf_path).name}: {len(result.molecules)} molecule(s), "
            f"{len(result.reactions)} reaction(s).{warn}"
        )

    def _on_extract_failed(self, message: str) -> None:
        self._extract_status.setText(message)
        self.status_label.setText("Extraction failed.")
        if self._result_tabs.count() == 0:
            self._startup_page.set_loading(False, message)
            self._results_stack.setCurrentWidget(self._startup_page)
        QMessageBox.critical(self, APP_NAME, message)

    def _on_extract_cancelled(self) -> None:
        self._extract_status.setText("Extraction cancelled.")
        self.status_label.setText("Extraction cancelled.")
        if self._result_tabs.count() == 0:
            self._startup_page.set_loading(False)
            self._results_stack.setCurrentWidget(self._startup_page)

    def _result_tab_widgets(self) -> list[ExtractionResultTab]:
        return [
            widget
            for index in range(self._result_tabs.count())
            if isinstance(widget := self._result_tabs.widget(index), ExtractionResultTab)
        ]

    def _set_active_result_tab(self, index: int | None) -> None:
        result_tab = (
            self._result_tabs.widget(index)
            if index is not None and 0 <= index < self._result_tabs.count()
            else None
        )
        if not isinstance(result_tab, ExtractionResultTab):
            result_tab = None
        self._active_result_tab = result_tab
        active_tables = result_tab or self._empty_result_tab
        self._mol_table = active_tables.molecule_table
        self._rxn_table = active_tables.reaction_table
        self._result = result_tab.result if result_tab is not None else None
        if result_tab is None:
            self._clear_detail()
            self._detail_panel.hide()
        else:
            self._detail_panel.show()

    def _on_result_tab_changed(self, index: int) -> None:
        self._set_active_result_tab(index)
        if self._active_result_tab is None:
            if self._result_tabs.count() == 0:
                self._results_stack.setCurrentWidget(self._startup_page)
            return
        self._refresh_selected_detail()

    def _show_result_tab_context_menu(self, position: QPoint) -> None:
        index = self._result_tabs.tabBar().tabAt(position)
        if index < 0:
            return
        menu = QMenu(self)
        close_action = menu.addAction("Close tab")
        if menu.exec(self._result_tabs.tabBar().mapToGlobal(position)) is close_action:
            self._confirm_delete_result_tab(index)

    def _confirm_delete_result_tab(self, index: int) -> None:
        if not 0 <= index < self._result_tabs.count():
            return
        name = self._result_tabs.tabText(index)
        answer = QMessageBox.question(
            self,
            APP_NAME,
            f"Delete '{name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        result_tab = self._result_tabs.widget(index)
        self._result_tabs.removeTab(index)
        result_tab.deleteLater()
        if self._result_tabs.count() == 0:
            self._set_active_result_tab(None)
            self._results_stack.setCurrentWidget(self._startup_page)

    def _on_result_tab_selected(self, *_args) -> None:
        self._refresh_selected_detail()

    def _on_molecule_selected(self, *_args) -> None:
        self._refresh_selected_detail()

    def _selected_molecule(self) -> ExtractedMolecule | None:
        indexes = self._mol_table.selectionModel().selectedRows()
        if not indexes:
            return None
        return self._mol_table.molecule_model().molecule_at(indexes[0].row())

    def _refresh_selected_detail(self) -> None:
        rec = self._selected_molecule()
        if rec is None:
            self._clear_detail()
            return
        mol = parse_mol(smiles=rec.smiles, molfile=rec.molfile)
        png = b""
        if mol is not None:
            try:
                png = render_molecule_png(mol, DETAIL_STRUCTURE_WIDTH, DETAIL_STRUCTURE_HEIGHT)
            except Exception:
                logger.debug("Detail structure render failed", exc_info=True)
        if png:
            self._detail_structure.setPixmap(pixmap_from_png(png))
            self._detail_structure.setText("")
        else:
            self._detail_structure.setPixmap(QPixmap())
            self._detail_structure.setText("No structure")
        if rec.crop_png:
            crop = pixmap_from_png(rec.crop_png)
            self._detail_crop.setPixmap(
                crop.scaled(320, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            self._detail_crop.setText("")
            self._detail_crop_card.show()
        else:
            self._detail_crop.setPixmap(QPixmap())
            self._detail_crop.setText("—")
            self._detail_crop_card.hide()
        page = "; ".join(str(page_number) for page_number in rec.page_numbers) or "—"
        score = f"{molecule_quality_score(rec):.3f}"
        mw = "—" if rec.molecular_weight is None else f"{rec.molecular_weight:.3f}"
        source = "; ".join(rec.sources) if rec.sources else rec.source
        values = {
            "Identifier": rec.identifier or "—",
            "Page": page,
            "Source": source or "—",
            "Quality": score,
            "Formula": rec.formula or "—",
            "Molecular weight": mw,
            "InChIKey": rec.inchi_key or "—",
        }
        for name, value in values.items():
            self._detail_values[name].setText(value)

    def _clear_detail(self) -> None:
        self._detail_structure.setPixmap(QPixmap())
        self._detail_structure.setText("Select a molecule")
        self._detail_crop.setPixmap(QPixmap())
        self._detail_crop.setText("—")
        self._detail_crop_card.hide()
        for value in self._detail_values.values():
            value.setText("—")

    def _require_molecules(self) -> list[ExtractedMolecule] | None:
        mols = self._mol_table.molecule_model().molecules()
        if not mols:
            QMessageBox.information(self, APP_NAME, "No extracted molecules to export.")
            return None
        return mols

    def _export_molecules(
        self,
        dialog_title: str,
        file_filter: str,
        writer: Callable[[str, list[ExtractedMolecule]], int | None],
        success_message: Callable[[str, int | None], str],
    ) -> None:
        molecules = self._require_molecules()
        if molecules is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, dialog_title, self._last_dir(), file_filter
        )
        if not path:
            return
        try:
            result = writer(path, molecules)
        except Exception as exc:
            logger.exception("Could not export molecules to %s", path)
            QMessageBox.critical(
                self,
                APP_NAME,
                f"Could not export to:\n{path}\n\n{exc}",
            )
            return
        self._set_last_dir(path)
        self.status_label.setText(success_message(path, result))

    def export_csv(self) -> None:
        self._export_molecules(
            "Export CSV",
            "CSV files (*.csv)",
            write_csv,
            lambda path, _result: f"Wrote {Path(path).name}",
        )

    def export_sdf(self) -> None:
        self._export_molecules(
            "Export SDF",
            "SDF files (*.sdf)",
            write_sdf,
            lambda path, count: f"Wrote {count or 0} molecule(s) to {Path(path).name}",
        )

    def export_smi(self) -> None:
        self._export_molecules(
            "Export SMILES",
            "SMILES files (*.smi *.txt)",
            write_smi,
            lambda path, _result: f"Wrote {Path(path).name}",
        )
