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
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QActionGroup, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .. import __version__
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
from .dialogs.custom_theme import CustomThemeDialog
from .dialogs.font_settings import FontSettingsDialog
from .dialogs.structure_settings import StructureSettingsDialog
from .molecule_table import MoleculeTableView, pixmap_from_png
from .qt_widget_utils import apply_monospace_to_text_edit
from .theme import (
    THEME_DARK,
    THEME_GROOVY,
    THEME_LIGHT,
    apply_application_font_pt,
    apply_application_theme,
    current_theme_name,
    custom_theme_display_name,
    default_app_font_pt,
    default_table_font_pt,
    detail_panel_stylesheet,
    extract_panel_stylesheet,
    is_custom_theme_id,
    list_custom_theme_names,
    load_saved_app_font_pt,
    load_saved_table_font_pt,
    load_saved_theme_name,
    make_custom_theme_id,
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
_DETAIL_PANEL_WIDTH = 340


class MainWindow(QMainWindow):
    """Patent extraction workspace with MolManager Fusion themes."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1400, 820)
        self._pdf_path: str | None = None
        self._result: ExtractionResult | None = None
        self._worker: ExtractWorker | None = None
        self._app_font_pt = load_saved_app_font_pt()
        apply_application_font_pt(self._app_font_pt)
        self._gui_theme = load_saved_theme_name()
        self._table_font_pt = load_saved_table_font_pt()
        w, h = load_saved_structure_size()
        set_structure_size(w, h, persist=False)

        self._build_menus()
        self._build_central()
        apply_application_theme(QApplication.instance(), self._gui_theme)
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
        file_menu = menubar.addMenu("&File")
        file_menu.addAction(QAction("&Open PDF…", self, shortcut="Ctrl+O", triggered=self.open_pdf))
        file_menu.addSeparator()
        file_menu.addAction(QAction("Export &CSV…", self, triggered=self.export_csv))
        file_menu.addAction(QAction("Export S&DF…", self, triggered=self.export_sdf))
        file_menu.addAction(QAction("Export S&MILES…", self, triggered=self.export_smi))
        file_menu.addSeparator()
        file_menu.addAction(QAction("E&xit", self, shortcut="Ctrl+Q", triggered=self.close))

        settings_menu = menubar.addMenu("&Settings")
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
        self._custom_theme_actions: dict[str, QAction] = {}
        self._act_customize_colors = QAction(
            "Custom Colors…", self, triggered=self.open_custom_theme_dialog
        )
        self._rebuild_gui_theme_menu()
        settings_menu.addSeparator()
        settings_menu.addAction(
            QAction("&Structure…", self, triggered=self.open_structure_settings)
        )
        settings_menu.addAction(QAction("&Font…", self, triggered=self.open_font_dialog))

        help_menu = menubar.addMenu("&Help")
        help_menu.addAction(QAction("&User Guide", self, triggered=self.show_user_guide))

    def _rebuild_gui_theme_menu(self) -> None:
        menu = self._gui_menu
        menu.clear()
        for act in list(self._custom_theme_actions.values()):
            self._theme_action_group.removeAction(act)
        self._custom_theme_actions = {}
        menu.addAction(self._act_theme_light)
        menu.addAction(self._act_theme_dark)
        menu.addAction(self._act_theme_groovy)
        names = list_custom_theme_names()
        if names:
            menu.addSeparator()
            for name in names:
                act = QAction(name, self, checkable=True)
                theme_id = make_custom_theme_id(name)
                act.triggered.connect(lambda *_a, tid=theme_id: self._set_gui_theme(tid))
                self._theme_action_group.addAction(act)
                self._custom_theme_actions[name] = act
                menu.addAction(act)
        menu.addSeparator()
        menu.addAction(self._act_customize_colors)
        self._sync_theme_menu_checks()

    def _sync_theme_menu_checks(self) -> None:
        name = getattr(self, "_gui_theme", current_theme_name()) or current_theme_name()
        self._act_theme_light.setChecked(name == THEME_LIGHT)
        self._act_theme_dark.setChecked(name == THEME_DARK)
        self._act_theme_groovy.setChecked(name == THEME_GROOVY)
        custom_name = custom_theme_display_name(name) if is_custom_theme_id(name) else None
        for label, act in self._custom_theme_actions.items():
            act.setChecked(custom_name is not None and label == custom_name)

    def _build_central(self) -> None:
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_extract_panel())
        splitter.addWidget(self._build_results_tabs())
        splitter.addWidget(self._build_detail_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([_EXTRACT_PANEL_WIDTH, 760, _DETAIL_PANEL_WIDTH])
        self.setCentralWidget(splitter)

    def _build_extract_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("ExtractPanel")
        panel.setMinimumWidth(240)
        panel.setMaximumWidth(360)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title = QLabel("Extract")
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)

        self._pdf_label = QLabel("No PDF selected")
        self._pdf_label.setWordWrap(True)
        layout.addWidget(self._pdf_label)

        open_btn = QPushButton("Open PDF…")
        open_btn.clicked.connect(self.open_pdf)
        layout.addWidget(open_btn)

        self._chk_figures = QCheckBox("Molecules from figures")
        self._chk_figures.setChecked(True)
        self._chk_text = QCheckBox("Names from Text")
        self._chk_text.setChecked(True)
        self._chk_corefs = QCheckBox("Figure–label coreferences")
        self._chk_corefs.setChecked(False)
        self._chk_reactions = QCheckBox("Reactions")
        self._chk_reactions.setChecked(False)
        self._chk_merge = QCheckBox("Merge duplicates (InChIKey)")
        self._chk_merge.setChecked(True)
        layout.addWidget(self._chk_figures)
        layout.addWidget(self._chk_text)
        layout.addWidget(self._chk_corefs)
        layout.addWidget(self._chk_reactions)
        layout.addWidget(self._chk_merge)

        all_range_row = QHBoxLayout()
        all_range_row.setContentsMargins(0, 0, 0, 0)
        all_range_row.setSpacing(12)
        self._all_pages_chk = QCheckBox("All Pages")
        self._all_pages_chk.setChecked(True)
        self._all_pages_chk.setToolTip("Process the full PDF from the first page onward.")
        self._all_structures_chk = QCheckBox("All Structures")
        self._all_structures_chk.setChecked(True)
        self._all_structures_chk.setToolTip("Ignore the structure cap and extract all detected molecules.")
        all_range_row.addWidget(self._all_pages_chk)
        all_range_row.addWidget(self._all_structures_chk)
        layout.addLayout(all_range_row)

        form = QFormLayout()
        form.setSpacing(4)

        self._device_combo = QComboBox()
        self._device_combo.setToolTip(
            "CUDA appears only when a compatible NVIDIA GPU and drivers are available, "
            "otherwise CPU is used."
        )
        self._device_combo.addItem("CPU", "cpu")
        if self._cuda_available():
            self._device_combo.addItem("CUDA (GPU)", "cuda")
            self._device_combo.setCurrentIndex(self._device_combo.findData("cuda"))
        form.addRow("Device:", self._device_combo)

        self._crop_margin_spin = QDoubleSpinBox()
        self._crop_margin_spin.setRange(0.0, 50.0)
        self._crop_margin_spin.setDecimals(1)
        self._crop_margin_spin.setSingleStep(1.0)
        self._crop_margin_spin.setSuffix("%")
        self._crop_margin_spin.setValue(DEFAULT_MOLECULE_CROP_MARGIN * 100.0)
        self._crop_margin_spin.setToolTip(
            "Expand each detection box by this percentage in every direction before cropping."
        )
        form.addRow("Crop expansion:", self._crop_margin_spin)

        self._first_page_spin = QSpinBox()
        self._first_page_spin.setRange(1, 9999)
        self._first_page_spin.setValue(1)
        self._first_page_spin.setToolTip("1-based page to start on.")
        form.addRow("First page:", self._first_page_spin)

        self._pages_spin = QSpinBox()
        self._pages_spin.setRange(0, 9999)
        self._pages_spin.setValue(5)
        self._pages_spin.setSpecialValueText("All")
        self._pages_spin.setToolTip(
            "How many pages to process from First page. 0 = through the end."
        )
        form.addRow("Page count:", self._pages_spin)

        self._max_mols_spin = QSpinBox()
        self._max_mols_spin.setRange(0, 99999)
        self._max_mols_spin.setValue(50)
        self._max_mols_spin.setSpecialValueText("All")
        self._max_mols_spin.setToolTip("Stop after this many structures. 0 = no cap.")
        form.addRow("Max structures:", self._max_mols_spin)
        layout.addLayout(form)

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

    def _build_results_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        self._mol_table = MoleculeTableView()
        self._mol_table.selectionModel().selectionChanged.connect(self._on_molecule_selected)
        tabs.addTab(self._mol_table, "Molecules")

        self._rxn_table = QTableWidget(0, 5)
        self._rxn_table.setHorizontalHeaderLabels(
            ["Page", "Reactants", "Products", "Conditions", "Source"]
        )
        self._rxn_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._rxn_table.setAlternatingRowColors(True)
        self._rxn_table.horizontalHeader().setStretchLastSection(True)
        tabs.addTab(self._rxn_table, "Reactions")
        self._tabs = tabs
        return tabs

    def _build_detail_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("DetailPanel")
        panel.setMinimumWidth(280)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        title = QLabel("Details")
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)

        self._detail_structure = QLabel()
        self._detail_structure.setAlignment(Qt.AlignCenter)
        self._detail_structure.setMinimumHeight(DETAIL_STRUCTURE_HEIGHT)
        self._detail_structure.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._detail_structure.setText("Select a molecule")
        layout.addWidget(self._detail_structure)

        crop_caption = QLabel("Patent crop")
        layout.addWidget(crop_caption)
        self._detail_crop = QLabel("—")
        self._detail_crop.setAlignment(Qt.AlignCenter)
        self._detail_crop.setMinimumHeight(120)
        layout.addWidget(self._detail_crop)

        self._detail_meta = QLabel("")
        self._detail_meta.setWordWrap(True)
        self._detail_meta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self._detail_meta)

        self._detail_panel = panel
        self._clear_detail()
        return panel

    def refresh_theme(self) -> None:
        """Hook for live light/dark/groovy switches."""
        app = QApplication.instance()
        if app is not None:
            self.setPalette(app.palette())
            self.setAutoFillBackground(False)
            self.setAttribute(Qt.WA_StyledBackground, False)
        self.setStyleSheet("")

        menu_bar = self.menuBar()
        if menu_bar is not None:
            menu_bar.setStyleSheet("")
            menu_bar.setAutoFillBackground(False)
            menu_bar.setAttribute(Qt.WA_StyledBackground, False)

        extract = getattr(self, "_extract_panel", None)
        if extract is not None:
            extract.setStyleSheet(extract_panel_stylesheet())
        detail = getattr(self, "_detail_panel", None)
        if detail is not None:
            detail.setStyleSheet(detail_panel_stylesheet())
        table = getattr(self, "_mol_table", None)
        if table is not None:
            table.refresh_theme()
        if getattr(self, "_table_font_pt", None) is not None:
            self._apply_table_font()
        self.update()
        if app is not None:
            app.processEvents()

    def _set_gui_theme(self, theme: str) -> None:
        app = QApplication.instance()
        theme = apply_application_theme(app, theme)
        self._gui_theme = theme
        save_theme_name(theme)
        if app is not None:
            self.setPalette(app.palette())
            self.setStyleSheet("")
            self.update()
        self._sync_theme_menu_checks()
        self.refresh_theme()
        apply_application_font_pt(int(self._app_font_pt or default_app_font_pt()))

    def open_custom_theme_dialog(self) -> None:
        dlg = CustomThemeDialog(self)
        accepted = dlg.exec() == QDialog.Accepted
        deleted = dlg.deleted_theme_name()
        saved = dlg.saved_theme_name() if accepted else None
        if deleted:
            cur = current_theme_name()
            if is_custom_theme_id(cur) and custom_theme_display_name(cur) == deleted:
                self._set_gui_theme(THEME_LIGHT)
        if deleted or saved:
            self._rebuild_gui_theme_menu()
        if saved:
            self._set_gui_theme(make_custom_theme_id(saved))
            self.status_label.setText(f'Saved custom theme "{saved}".')

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
        self._mol_table.apply_structure_layout()
        self._mol_table.molecule_model().rerender_structures()
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
        self._mol_table.apply_table_font(self._table_font_pt)
        font = self._rxn_table.font()
        font.setPointSize(int(self._table_font_pt))
        self._rxn_table.setFont(font)

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
            "Open <b>Settings → GUI</b> to switch between Light, Dark, and Groovy themes, "
            "or choose custom color schemes. Structure rendering and font settings are also "
            "available under Settings.</p>"
            "<p><b>Tips</b><br>"
            "- Install Poppler for PDF rendering support.<br>"
            "- On Python 3.10/3.11, OpenChemIE may require a manual torch 2.x workaround "
            "before installing from its Git repo.<br>"
            "- If the Extract panel warns that OpenChemIE is unavailable, install the "
            "project requirements again in the active venv.</p>",
        )

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
        pages = int(self._pages_spin.value())
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
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.start()

    def cancel_extraction(self) -> None:
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            self._extract_status.setText("Cancel requested — waiting for the current step…")
            self.status_label.setText("Cancel requested.")

    def _set_busy(self, busy: bool) -> None:
        self._extract_btn.setEnabled(not busy)
        self._cancel_btn.setEnabled(busy)
        self._progress.setVisible(busy)

    def _on_extract_progress(self, message: str) -> None:
        self._extract_status.setText(message)
        self.status_label.setText(message)

    def _on_extract_finished(self, result: object) -> None:
        if not isinstance(result, ExtractionResult):
            self._on_extract_failed("Unexpected extraction result.")
            return
        self._result = result
        self._mol_table.molecule_model().set_molecules(result.molecules)
        self._mol_table.apply_structure_layout()
        self._fill_reactions(result)
        if result.molecules:
            self._mol_table.selectRow(0)
        else:
            self._clear_detail()
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
        QMessageBox.critical(self, APP_NAME, message)

    def _fill_reactions(self, result: ExtractionResult) -> None:
        table = self._rxn_table
        table.setRowCount(0)
        for rxn in result.reactions:
            row = table.rowCount()
            table.insertRow(row)
            values = [
                "" if rxn.page is None else str(rxn.page),
                " + ".join(rxn.reactants),
                " + ".join(rxn.products),
                rxn.conditions,
                rxn.source,
            ]
            for col, value in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(value))
        self._tabs.setTabText(1, f"Reactions ({len(result.reactions)})")
        self._tabs.setTabText(0, f"Molecules ({len(result.molecules)})")

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
        else:
            self._detail_crop.setPixmap(QPixmap())
            self._detail_crop.setText("—")
        page = "—" if rec.page is None else str(rec.page)
        score = f"{molecule_quality_score(rec):.3f}"
        mw = "—" if rec.molecular_weight is None else f"{rec.molecular_weight:.3f}"
        source = "; ".join(rec.sources) if rec.sources else rec.source
        self._detail_meta.setText(
            f"Identifier: {rec.identifier or '—'}\n"
            f"Page: {page}    Source: {source}    Quality: {score}\n"
            f"Formula: {rec.formula or '—'}    MW: {mw}\n"
            f"InChIKey: {rec.inchi_key or '—'}"
        )

    def _clear_detail(self) -> None:
        self._detail_structure.setPixmap(QPixmap())
        self._detail_structure.setText("Select a molecule")
        self._detail_crop.setPixmap(QPixmap())
        self._detail_crop.setText("—")
        self._detail_meta.setText("")

    def _require_molecules(self) -> list[ExtractedMolecule] | None:
        mols = self._mol_table.molecule_model().molecules()
        if not mols:
            QMessageBox.information(self, APP_NAME, "No extracted molecules to export.")
            return None
        return mols

    def export_csv(self) -> None:
        mols = self._require_molecules()
        if mols is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", self._last_dir(), "CSV files (*.csv)"
        )
        if not path:
            return
        write_csv(path, mols)
        self._set_last_dir(path)
        self.status_label.setText(f"Wrote {Path(path).name}")

    def export_sdf(self) -> None:
        mols = self._require_molecules()
        if mols is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export SDF", self._last_dir(), "SDF files (*.sdf)"
        )
        if not path:
            return
        n = write_sdf(path, mols)
        self._set_last_dir(path)
        self.status_label.setText(f"Wrote {n} molecule(s) to {Path(path).name}")

    def export_smi(self) -> None:
        mols = self._require_molecules()
        if mols is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export SMILES", self._last_dir(), "SMILES files (*.smi *.txt)"
        )
        if not path:
            return
        write_smi(path, mols)
        self._set_last_dir(path)
        self.status_label.setText(f"Wrote {Path(path).name}")
