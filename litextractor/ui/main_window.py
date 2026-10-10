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

"""Main window: extract panel, results tabs, and detail pane."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
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
from ..export import write_csv, write_sdf, write_smi
from ..models import ExtractOptions, ExtractedMolecule, ExtractionResult
from ..structure_dimensions import DETAIL_STRUCTURE_HEIGHT
from ..workers.cuda_probe_worker import CudaAvailabilityWorker
from .dialogs.citations import CitationsDialog
from .detail_panel_presenter import DetailPanelPresenter
from .extraction_controller import ExtractionController
from .result_tabs_controller import ResultTabsController
from .startup_page import StartupPage
from .theme import DETAIL_PANEL_STYLESHEET, EXTRACT_PANEL_STYLESHEET

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .extraction_result_tab import ExtractionResultTab

APP_NAME = "LitExtractor"

_EXTRACT_PANEL_WIDTH = 280
_DETAIL_PANEL_WIDTH = 420

# Labels of the rows in the detail pane's "Molecule information" card, in display order.
_DETAIL_FIELD_NAMES = (
    "Identifier",
    "Page",
    "Source",
    "Quality",
    "Formula",
    "Molecular weight",
    "InChIKey",
)

_USER_GUIDE_HTML = (
    "<h3>LitExtractor User Guide</h3>"
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
    "<p><b>Tips</b><br>"
    "- Install Poppler for PDF rendering support.<br>"
    "- On Python 3.10/3.11, OpenChemIE may require a manual torch 2.x workaround "
    "before installing from its Git repo.<br>"
    "- If the Extract panel warns that OpenChemIE is unavailable, install the "
    "project requirements again in the active venv.</p>"
)


def _build_detail_card(title: str) -> tuple[QFrame, QVBoxLayout]:
    """Create a titled card for the detail pane and return it with its content layout."""
    card = QFrame()
    card.setObjectName("DetailCard")
    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(10, 8, 10, 10)
    card_layout.setSpacing(6)
    title_label = QLabel(title)
    title_label.setObjectName("DetailCardTitle")
    card_layout.addWidget(title_label)
    return card, card_layout


class MainWindow(QMainWindow):
    """Patent extraction workspace: options on the left, results in the center, details right."""

    def __init__(self) -> None:
        """Build the window and wire up the controllers that run extraction and show results."""
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1400, 820)
        self._pdf_path: str | None = None
        self._last_dir = str(Path.home())
        self._active_result_tab: ExtractionResultTab | None = None
        self._active_molecule_table = None
        self._cuda_probe_started = False
        self._cuda_worker: CudaAvailabilityWorker | None = None
        self._device_selection_touched = False

        self._build_menus()
        self._build_central()
        self._detail_presenter = DetailPanelPresenter(
            detail_structure=self._detail_structure,
            detail_crop=self._detail_crop,
            detail_crop_card=self._detail_crop_card,
            detail_values=self._detail_values,
        )
        self._results_controller = ResultTabsController(
            parent=self,
            app_name=APP_NAME,
            result_tabs=self._result_tabs,
            results_stack=self._results_stack,
            startup_page=self._startup_page,
            on_molecule_selected=self._refresh_selected_detail,
        )
        self._extraction_controller = ExtractionController(
            parent=self,
            app_name=APP_NAME,
            extract_button=self._extract_button,
            cancel_button=self._cancel_button,
            progress_bar=self._progress_bar,
            status_label=self.status_label,
            result_tabs=self._result_tabs,
            startup_page=self._startup_page,
            results_stack=self._results_stack,
        )
        self._set_active_result_tab(None)
        self.statusBar().hide()

    # ------------------------------------------------------------------ construction

    def _build_menus(self) -> None:
        """Create the File (open/export/exit) and Help (guide/citations) menus."""
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

        self._help_menu = menubar.addMenu("&Help")
        help_menu = self._help_menu
        help_menu.addAction(QAction("&User Guide", self, triggered=self.show_user_guide))
        help_menu.addAction(QAction("&Citations", self, triggered=self.show_citations))

    def _build_central(self) -> None:
        """Lay out the three columns: extract panel, results area, and detail panel."""
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
        """Build the left panel of extraction options, action buttons, progress, and status."""
        panel = QFrame()
        panel.setObjectName("ExtractPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        layout.addWidget(self._build_pdf_group())
        layout.addWidget(self._build_sources_group())
        layout.addWidget(self._build_page_range_group())
        layout.addWidget(self._build_structure_limit_group())
        layout.addWidget(self._build_processing_group())
        layout.addLayout(self._build_action_buttons())

        self._sync_page_range_enabled_state()
        self._sync_structure_limit_enabled_state()
        self._all_pages_checkbox.toggled.connect(self._sync_page_range_enabled_state)
        self._all_structures_checkbox.toggled.connect(self._sync_structure_limit_enabled_state)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch(1)
        self._extract_panel = panel
        panel.setStyleSheet(EXTRACT_PANEL_STYLESHEET)
        return panel

    def _build_pdf_group(self) -> QGroupBox:
        """Build the group that shows the selected PDF and its Open button."""
        group = QGroupBox("PDF")
        group_layout = QVBoxLayout(group)
        self._pdf_label = QLabel("No PDF selected")
        self._pdf_label.setWordWrap(True)
        open_button = QPushButton("Open PDF…")
        open_button.clicked.connect(self.open_pdf)
        group_layout.addWidget(self._pdf_label)
        group_layout.addWidget(open_button)
        return group

    def _build_sources_group(self) -> QGroupBox:
        """Build the checkboxes choosing which extractors run and whether to merge duplicates."""
        group = QGroupBox("Extract")
        group_layout = QVBoxLayout(group)
        self._figures_checkbox = QCheckBox("Molecules from figures")
        self._figures_checkbox.setChecked(True)
        self._text_checkbox = QCheckBox("Names from Text")
        self._text_checkbox.setChecked(True)
        self._corefs_checkbox = QCheckBox("Figure–label coreferences")
        self._corefs_checkbox.setChecked(True)
        self._reactions_checkbox = QCheckBox("Reactions")
        self._reactions_checkbox.setChecked(False)
        self._merge_checkbox = QCheckBox("Merge duplicates (InChIKey)")
        self._merge_checkbox.setChecked(True)
        for checkbox in (
            self._figures_checkbox,
            self._text_checkbox,
            self._corefs_checkbox,
            self._reactions_checkbox,
            self._merge_checkbox,
        ):
            group_layout.addWidget(checkbox)
        return group

    def _build_page_range_group(self) -> QGroupBox:
        """Build the controls for processing all pages or a first-page/page-count window."""
        group = QGroupBox("Page range")
        group_layout = QVBoxLayout(group)
        self._all_pages_checkbox = QCheckBox("All Pages")
        self._all_pages_checkbox.setChecked(True)
        self._all_pages_checkbox.setToolTip("Process the full PDF from the first page onward.")
        group_layout.addWidget(self._all_pages_checkbox)

        form = QFormLayout()
        form.setSpacing(4)
        self._first_page_spinbox = QSpinBox()
        self._first_page_spinbox.setRange(1, 9999)
        self._first_page_spinbox.setValue(1)
        self._first_page_spinbox.setToolTip("1-based page to start on.")
        form.addRow("First page:", self._first_page_spinbox)

        self._page_count_spinbox = QSpinBox()
        self._page_count_spinbox.setRange(0, 9999)
        self._page_count_spinbox.setValue(5)
        self._page_count_spinbox.setSpecialValueText("All")
        self._page_count_spinbox.setToolTip(
            "How many pages to process from First page. 0 = through the end."
        )
        form.addRow("Page count:", self._page_count_spinbox)
        group_layout.addLayout(form)
        return group

    def _build_structure_limit_group(self) -> QGroupBox:
        """Build the controls for capping how many structures are extracted."""
        group = QGroupBox("Structure limit")
        group_layout = QVBoxLayout(group)
        self._all_structures_checkbox = QCheckBox("All Structures")
        self._all_structures_checkbox.setChecked(True)
        self._all_structures_checkbox.setToolTip(
            "Ignore the structure cap and extract all detected molecules."
        )
        group_layout.addWidget(self._all_structures_checkbox)

        form = QFormLayout()
        form.setSpacing(4)
        self._max_structures_spinbox = QSpinBox()
        self._max_structures_spinbox.setRange(0, 99999)
        self._max_structures_spinbox.setValue(50)
        self._max_structures_spinbox.setSpecialValueText("All")
        self._max_structures_spinbox.setToolTip("Stop after this many structures. 0 = no cap.")
        form.addRow("Max structures:", self._max_structures_spinbox)
        group_layout.addLayout(form)
        return group

    def _build_processing_group(self) -> QGroupBox:
        """Build the compute-device selector and the molecule crop-expansion control."""
        group = QGroupBox("Processing")
        form = QFormLayout(group)
        form.setSpacing(4)

        self._device_combobox = QComboBox()
        self._device_combobox.setToolTip(
            "CUDA is checked in the background after startup. CPU is available immediately; "
            "CUDA appears when a compatible NVIDIA GPU and drivers are available."
        )
        self._device_combobox.addItem("CPU", "cpu")
        self._device_combobox.activated.connect(self._mark_device_selection_touched)
        form.addRow("Device:", self._device_combobox)

        self._crop_margin_spinbox = QDoubleSpinBox()
        self._crop_margin_spinbox.setRange(0.0, 50.0)
        self._crop_margin_spinbox.setDecimals(1)
        self._crop_margin_spinbox.setSingleStep(1.0)
        self._crop_margin_spinbox.setSuffix("%")
        self._crop_margin_spinbox.setValue(DEFAULT_MOLECULE_CROP_MARGIN * 100.0)
        self._crop_margin_spinbox.setToolTip(
            "Expand each detection box by this percentage in every direction before cropping."
        )
        form.addRow("Crop expansion:", self._crop_margin_spinbox)
        return group

    def _build_action_buttons(self) -> QHBoxLayout:
        """Build the Extract and Cancel buttons."""
        row = QHBoxLayout()
        self._extract_button = QPushButton("Extract")
        self._extract_button.setDefault(True)
        self._extract_button.clicked.connect(self.start_extraction)
        self._cancel_button = QPushButton("Cancel")
        self._cancel_button.setEnabled(False)
        self._cancel_button.clicked.connect(self.cancel_extraction)
        row.addWidget(self._extract_button)
        row.addWidget(self._cancel_button)
        return row

    def _build_results_tabs(self) -> QStackedWidget:
        """Build the center area: a startup page stacked with the tabs of extraction runs."""
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
        return self._results_stack

    def _build_detail_panel(self) -> QFrame:
        """Build the right panel describing the selected molecule (initially hidden)."""
        panel = QFrame()
        panel.setObjectName("DetailPanel")
        panel.setMinimumWidth(280)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)

        structure_card, structure_layout = _build_detail_card("Chemical structure")
        self._detail_structure = QLabel("Select a molecule")
        self._detail_structure.setAlignment(Qt.AlignCenter)
        self._detail_structure.setMinimumHeight(DETAIL_STRUCTURE_HEIGHT)
        self._detail_structure.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        structure_layout.addWidget(self._detail_structure)
        content_layout.addWidget(structure_card)

        self._detail_crop_card, crop_layout = _build_detail_card("Patent crop")
        self._detail_crop = QLabel("—")
        self._detail_crop.setObjectName("CropPreview")
        self._detail_crop.setAlignment(Qt.AlignCenter)
        self._detail_crop.setMinimumHeight(120)
        crop_layout.addWidget(self._detail_crop)
        content_layout.addWidget(self._detail_crop_card)

        information_card, information_layout = _build_detail_card("Molecule information")
        fields_layout = QGridLayout()
        fields_layout.setHorizontalSpacing(12)
        fields_layout.setVerticalSpacing(5)
        self._detail_values: dict[str, QLabel] = {}
        for row, field_name in enumerate(_DETAIL_FIELD_NAMES):
            field_label = QLabel(field_name)
            field_label.setObjectName("DetailFieldName")
            value_label = QLabel("—")
            value_label.setObjectName("DetailFieldValue")
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._detail_values[field_name] = value_label
            fields_layout.addWidget(field_label, row, 0, Qt.AlignTop)
            fields_layout.addWidget(value_label, row, 1)
        fields_layout.setColumnStretch(1, 1)
        information_layout.addLayout(fields_layout)
        content_layout.addWidget(information_card)
        content_layout.addStretch(1)
        scroll_area.setWidget(content)
        layout.addWidget(scroll_area, 1)

        self._detail_panel = panel
        panel.setStyleSheet(DETAIL_PANEL_STYLESHEET)
        panel.hide()
        return panel

    # ------------------------------------------------------------------ help and files

    def show_user_guide(self) -> None:
        """Show the user guide dialog."""
        QMessageBox.information(self, f"{APP_NAME} User Guide", _USER_GUIDE_HTML)

    def show_citations(self) -> None:
        """Open the citation guide for the application and its core technology stack."""
        CitationsDialog(self).exec()

    def open_pdf(self) -> None:
        """Ask the user for a PDF and make it the document to extract."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open patent PDF",
            self._last_dir,
            "PDF files (*.pdf);;All files (*.*)",
        )
        if not path:
            return
        self._set_pdf_path(path)

    def _set_pdf_path(self, path: str) -> None:
        """Remember the chosen PDF, its folder, and show its name in the panel."""
        self._pdf_path = path
        self._last_dir = str(Path(path).parent)
        self._pdf_label.setText(Path(path).name)
        self._pdf_label.setToolTip(path)
        self.status_label.setText(f"Opened {Path(path).name}")

    # ------------------------------------------------------------------ option controls

    def _sync_page_range_enabled_state(self) -> None:
        """Enable the page-range spin boxes only when "All Pages" is unchecked."""
        enabled = not self._all_pages_checkbox.isChecked()
        self._first_page_spinbox.setEnabled(enabled)
        self._page_count_spinbox.setEnabled(enabled)

    def _sync_structure_limit_enabled_state(self) -> None:
        """Enable the max-structures spin box only when "All Structures" is unchecked."""
        self._max_structures_spinbox.setEnabled(not self._all_structures_checkbox.isChecked())

    def start_cuda_probe(self) -> None:
        """Check CUDA in the background after the main window has been shown."""
        if self._cuda_probe_started:
            return
        app = QApplication.instance()
        if app is None:
            return

        self._cuda_probe_started = True
        worker = CudaAvailabilityWorker(app)
        self._cuda_worker = worker
        worker.availability_checked.connect(self._on_cuda_probe_finished)
        app.aboutToQuit.connect(lambda worker=worker: worker.wait())
        worker.start()

    def _mark_device_selection_touched(self, _index: int) -> None:
        """Record that the user chose a device, so CUDA detection will not override it."""
        self._device_selection_touched = True

    def _on_cuda_probe_finished(self, available: bool) -> None:
        """Offer CUDA in the device list, selecting it unless the user already chose a device."""
        if not available or self._device_combobox.findData("cuda") >= 0:
            return
        self._device_combobox.addItem("CUDA (GPU)", "cuda")
        if not self._device_selection_touched:
            self._device_combobox.setCurrentIndex(self._device_combobox.findData("cuda"))

    def _current_options(self) -> ExtractOptions:
        """Translate the extract-panel controls into extraction options."""
        max_structures = int(self._max_structures_spinbox.value())
        first_page = int(self._first_page_spinbox.value())
        page_count = int(self._page_count_spinbox.value())
        if self._all_pages_checkbox.isChecked():
            first_page = 1
            page_count = 0
        if self._all_structures_checkbox.isChecked():
            max_structures = 0
        return ExtractOptions(
            figures=self._figures_checkbox.isChecked(),
            text=self._text_checkbox.isChecked(),
            corefs=self._corefs_checkbox.isChecked(),
            reactions=self._reactions_checkbox.isChecked(),
            merge_by_inchi=self._merge_checkbox.isChecked(),
            first_page=first_page,
            num_pages=page_count if page_count > 0 else None,
            max_molecules=max_structures if max_structures > 0 else None,
            device=str(self._device_combobox.currentData() or "cpu"),
            crop_margin=max(0.0, float(self._crop_margin_spinbox.value()) / 100.0),
        )

    # ------------------------------------------------------------------ extraction

    def start_extraction(self) -> None:
        """Start extracting the chosen PDF (asking for one first) with the current options."""
        if not self._pdf_path:
            self.open_pdf()
            if not self._pdf_path:
                return
        options = self._current_options()
        if not (options.figures or options.text or options.reactions or options.corefs):
            QMessageBox.information(self, APP_NAME, "Select at least one extraction source.")
            return
        self._extraction_controller.start_worker(
            pdf_path=self._pdf_path,
            options=options,
            on_finished=self._on_extract_finished,
        )

    def cancel_extraction(self) -> None:
        """Ask the running extraction to stop."""
        self._extraction_controller.cancel_worker()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """Close now, or defer closing until a running extraction has stopped."""
        if self._extraction_controller.handle_close_event(event):
            return
        super().closeEvent(event)

    def _on_extract_finished(self, result: object) -> None:
        """Show a finished extraction in a new result tab and report its warnings."""
        if not isinstance(result, ExtractionResult):
            self._extraction_controller.handle_failed("Unexpected extraction result.")
            return
        result_tab = self._results_controller.add_result(result)
        self._set_active_result_tab(self._result_tabs.currentIndex())
        self._detail_panel.show()
        if result.molecules:
            result_tab.molecule_table.selectRow(0)
        else:
            self._detail_presenter.clear_detail()
        warnings_suffix = ""
        if result.warnings:
            warnings_suffix = " Warnings: " + "; ".join(result.warnings)
            QMessageBox.warning(self, APP_NAME, "\n".join(result.warnings))
        self.status_label.setText(
            f"{Path(result.pdf_path).name}: {len(result.molecules)} molecule(s), "
            f"{len(result.reactions)} reaction(s).{warnings_suffix}"
        )

    # ------------------------------------------------------------------ result tabs

    def _set_active_result_tab(self, index: int | None) -> None:
        """Track the tab at ``index`` as active and show or hide the detail panel accordingly."""
        result_tab = self._results_controller.active_result_tab(index)
        self._active_result_tab = result_tab
        self._active_molecule_table = result_tab.molecule_table if result_tab is not None else None
        if result_tab is None:
            self._detail_presenter.clear_detail()
            self._detail_panel.hide()
        else:
            self._detail_panel.show()

    def _on_result_tab_changed(self, index: int) -> None:
        """Follow the user switching result tabs."""
        self._set_active_result_tab(index)
        if self._active_result_tab is None:
            if self._result_tabs.count() == 0:
                self._results_controller.set_startup_view()
            return
        self._refresh_selected_detail()

    def _show_result_tab_context_menu(self, position: QPoint) -> None:
        """Offer to close the result tab that was right-clicked."""
        index = self._results_controller.show_context_menu(position, menu_factory=QMenu)
        if index is not None:
            self._confirm_delete_result_tab(index)

    def _confirm_delete_result_tab(self, index: int) -> None:
        """Ask for confirmation, delete the tab, and re-sync the active tab and detail pane."""
        deleted = self._results_controller.confirm_delete(index)
        if not deleted:
            return
        if self._result_tabs.count() == 0:
            self._set_active_result_tab(None)
            self._results_controller.set_startup_view()
            return
        current_index = self._result_tabs.currentIndex()
        self._set_active_result_tab(current_index if current_index >= 0 else None)
        self._refresh_selected_detail()

    def _refresh_selected_detail(self, *_args: object) -> None:
        """Show the selected molecule of the active tab in the detail pane."""
        self._detail_presenter.refresh_selected_detail(self._active_molecule_table)

    # ------------------------------------------------------------------ export

    def _molecules_to_export(self) -> list[ExtractedMolecule] | None:
        """Return the active tab's molecules, or warn the user and return None if there are none."""
        molecules = (
            self._active_molecule_table.molecule_model().molecules()
            if self._active_molecule_table is not None
            else []
        )
        if not molecules:
            QMessageBox.information(self, APP_NAME, "No extracted molecules to export.")
            return None
        return molecules

    def _export_molecules(
        self,
        dialog_title: str,
        file_filter: str,
        write_file: Callable[[str, list[ExtractedMolecule]], int | None],
        success_message: Callable[[str, int | None], str],
    ) -> None:
        """Ask for a destination and export the active tab's molecules with ``write_file``.

        On success the destination folder is remembered and ``success_message`` is shown in the
        status label; on failure the error is shown and the remembered folder is unchanged.
        """
        molecules = self._molecules_to_export()
        if molecules is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, dialog_title, self._last_dir, file_filter)
        if not path:
            return
        try:
            write_result = write_file(path, molecules)
        except Exception as exc:
            logger.exception("Could not export molecules to %s", path)
            QMessageBox.critical(
                self,
                APP_NAME,
                f"Could not export to:\n{path}\n\n{exc}",
            )
            return
        self._last_dir = str(Path(path).parent)
        self.status_label.setText(success_message(path, write_result))

    def export_csv(self) -> None:
        """Export the active tab's molecules as CSV."""
        self._export_molecules(
            "Export CSV",
            "CSV files (*.csv)",
            write_csv,
            lambda path, _result: f"Wrote {Path(path).name}",
        )

    def export_sdf(self) -> None:
        """Export the active tab's molecules as an SDF file."""
        self._export_molecules(
            "Export SDF",
            "SDF files (*.sdf)",
            write_sdf,
            lambda path, count: f"Wrote {count or 0} molecule(s) to {Path(path).name}",
        )

    def export_smi(self) -> None:
        """Export the active tab's molecules as a SMILES file."""
        self._export_molecules(
            "Export SMILES",
            "SMILES files (*.smi *.txt)",
            write_smi,
            lambda path, _result: f"Wrote {Path(path).name}",
        )
