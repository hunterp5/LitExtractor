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

"""Qt runtime bootstrap tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from litextractor import bootstrap


@pytest.fixture
def windows_qt_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    executable = tmp_path / "venv" / "Scripts" / "python.exe"
    executable.parent.mkdir(parents=True)
    monkeypatch.setattr(bootstrap.sys, "platform", "win32")
    monkeypatch.setattr(bootstrap.sys, "executable", str(executable))
    qt_package = tmp_path / "venv" / "Lib" / "site-packages" / "PySide6"
    platforms = qt_package / "plugins" / "platforms"
    platforms.mkdir(parents=True)
    return [qt_package, platforms]


def test_prepare_qt_runtime_retains_registered_dll_directory_handles(
    windows_qt_directories: list[Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    handles = [object(), object()]
    registrations: list[str] = []
    previous_handle_count = len(bootstrap._DLL_DIRECTORY_HANDLES)

    def register(directory: str) -> object:
        registrations.append(directory)
        return handles[len(registrations) - 1]

    monkeypatch.setattr(bootstrap.os, "add_dll_directory", register)
    monkeypatch.setenv("PATH", "original-path")
    try:
        bootstrap._prepare_qt_runtime()

        assert registrations == [str(path) for path in windows_qt_directories]
        assert bootstrap._DLL_DIRECTORY_HANDLES[previous_handle_count:] == handles
        path_entries = os.environ["PATH"].split(os.pathsep)
        assert all(str(path) in path_entries for path in windows_qt_directories)
    finally:
        del bootstrap._DLL_DIRECTORY_HANDLES[previous_handle_count:]


def test_prepare_qt_runtime_logs_registration_failure_and_continues(
    windows_qt_directories: list[Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    registrations: list[str] = []
    previous_handle_count = len(bootstrap._DLL_DIRECTORY_HANDLES)

    def register(directory: str) -> object:
        registrations.append(directory)
        if len(registrations) == 1:
            raise OSError("access denied")
        return object()

    monkeypatch.setattr(bootstrap.os, "add_dll_directory", register)
    try:
        bootstrap._prepare_qt_runtime()

        assert registrations == [str(path) for path in windows_qt_directories]
        assert "Could not register Qt DLL directory" in caplog.text
        assert len(bootstrap._DLL_DIRECTORY_HANDLES) == previous_handle_count + 1
    finally:
        del bootstrap._DLL_DIRECTORY_HANDLES[previous_handle_count:]


def test_prepare_qt_runtime_is_noop_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bootstrap.sys, "platform", "linux")

    def unexpected_registration(_directory: str) -> object:
        raise AssertionError("DLL directories are only registered on Windows")

    monkeypatch.setattr(bootstrap.os, "add_dll_directory", unexpected_registration)
    bootstrap._prepare_qt_runtime()


def test_startup_imports_do_not_load_model_or_rdkit_runtime() -> None:
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    code = (
        "import sys; from PySide6.QtWidgets import QApplication; "
        "from litextractor.bootstrap import MainWindow; "
        "app = QApplication([]); window = MainWindow(); "
        "assert not any("
        "name == 'rdkit' or name.startswith('rdkit.') for name in sys.modules"
        "); "
        "assert 'torch' not in sys.modules; assert 'openchemie' not in sys.modules; "
        "window.close(); app.quit()"
    )

    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        cwd=Path(__file__).resolve().parents[1],
    )
