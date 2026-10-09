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

"""Runtime setup and diagnostic tests; these do not load model weights."""

from __future__ import annotations

import importlib

from patentextractor import extraction, extraction_runtime


def test_missing_layoutparser_produces_actionable_diagnostic(ddr2_sub_pdf):
    error = ModuleNotFoundError("No module named 'layoutparser'")

    diagnostic = extraction_runtime.build_openchemie_import_diagnostic(
        error, pdf_path=str(ddr2_sub_pdf)
    )

    assert ddr2_sub_pdf.exists()
    assert "ddr2_sub.pdf" in diagnostic
    assert "layoutparser" in diagnostic.lower()
    assert "python -m pip install layoutparser" in diagnostic


def test_missing_openchemie_runtime_dependencies_detects_missing_modules(monkeypatch):
    def fake_find_spec(name: str):
        if name in {"easyocr", "IPython"}:
            return None
        return object()

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    missing = extraction_runtime.missing_openchemie_runtime_dependencies()

    assert "easyocr" in missing
    assert "IPython" in missing
    assert "pdftotext" not in missing


def test_openchemie_import_error_is_not_reported_as_missing_dependency():
    error = ImportError(
        "cannot import name 'safe_rotate_enlarged_img_size' from "
        "'albumentations.augmentations.geometric.functional'"
    )

    diagnostic = extraction_runtime.build_openchemie_import_diagnostic(
        error, pdf_path="ddr2_sub.pdf"
    )

    assert "missing dependency" not in diagnostic.lower()
    assert "albumentations" in diagnostic.lower()
    assert "incompatible" in diagnostic.lower()
    assert "ddr2_sub.pdf" in diagnostic


def test_pdftotext_missing_uses_windows_shim_guidance(monkeypatch):
    monkeypatch.setattr(extraction_runtime, "missing_openchemie_runtime_dependencies", lambda: [])

    diagnostic = extraction_runtime.build_openchemie_import_diagnostic(
        ModuleNotFoundError("No module named 'pdftotext'"),
        pdf_path="ddr2_sub.pdf",
    )

    assert "pdftotext" in diagnostic.lower()
    assert "pip install pdftotext" not in diagnostic.lower()
    assert "PyPDF2 shim" in diagnostic


def test_cuda_is_optional_and_falls_back_to_cpu(monkeypatch):
    monkeypatch.setattr(extraction_runtime, "cuda_available", lambda: False)

    assert extraction_runtime.cuda_available() is False
    assert extraction_runtime.resolve_torch_device("cuda") == "cpu"
    assert extraction_runtime.resolve_torch_device("cpu") == "cpu"


def test_extraction_reexports_runtime_helpers():
    assert extraction.cuda_available is extraction_runtime.cuda_available
    assert extraction.resolve_torch_device is extraction_runtime.resolve_torch_device
    assert extraction.load_openchemie is extraction_runtime.load_openchemie
    assert (
        extraction.missing_openchemie_runtime_dependencies
        is extraction_runtime.missing_openchemie_runtime_dependencies
    )
    assert (
        extraction.build_openchemie_import_diagnostic
        is extraction_runtime.build_openchemie_import_diagnostic
    )