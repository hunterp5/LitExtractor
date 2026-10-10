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

"""Tests for application settings migration."""

from __future__ import annotations

from PySide6.QtCore import QSettings

from litextractor.settings import _migrate_legacy_settings


def test_legacy_settings_migrate_once_without_overwriting_new_values(tmp_path):
    legacy = QSettings(str(tmp_path / "legacy.ini"), QSettings.IniFormat)
    current = QSettings(str(tmp_path / "current.ini"), QSettings.IniFormat)
    legacy.setValue("files/last_dir", "old-folder")
    legacy.setValue("gui/theme", "dark")
    current.setValue("gui/theme", "groovy")

    _migrate_legacy_settings(current, legacy)

    assert current.value("files/last_dir") == "old-folder"
    assert current.value("gui/theme") == "groovy"

    legacy.setValue("files/last_dir", "changed-old-folder")
    _migrate_legacy_settings(current, legacy)

    assert current.value("files/last_dir") == "old-folder"