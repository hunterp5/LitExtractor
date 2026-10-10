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

"""Pytest fixtures (Qt offscreen for headless runs)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="run tests that require external models or services",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-integration"):
        return
    skip_integration = pytest.mark.skip(reason="requires --run-integration")
    for item in items:
        if item.get_closest_marker("integration"):
            item.add_marker(skip_integration)


@pytest.fixture(scope="session")
def qapp():
    """Single QApplication for the test session."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(scope="session")
def ddr2_sub_pdf() -> Path:
    """Return the shared local patent sample, or skip tests that require it."""
    path = Path(__file__).resolve().parents[1] / "samples" / "ddr2_sub.pdf"
    if not path.is_file():
        pytest.skip("Local sample samples/ddr2_sub.pdf is required for this test.")
    return path
