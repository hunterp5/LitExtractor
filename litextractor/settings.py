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

"""Application settings identity and one-time migration from the previous namespace."""

from __future__ import annotations

from PySide6.QtCore import QSettings

SETTINGS_ORG = "LitExtractor"
SETTINGS_APP = "LitExtractor"

_LEGACY_SETTINGS_ORG = "PatentExtractor"
_LEGACY_SETTINGS_APP = "PatentExtractor"
_MIGRATION_KEY = "migration/legacy_settings_copied"


def _migrate_legacy_settings(settings: QSettings, legacy_settings: QSettings) -> None:
    """Copy old settings once, without replacing values already saved by LitExtractor."""
    if settings.value(_MIGRATION_KEY, False):
        return

    for key in legacy_settings.allKeys():
        if not settings.contains(key):
            settings.setValue(key, legacy_settings.value(key))

    settings.setValue(_MIGRATION_KEY, True)
    settings.sync()


def application_settings() -> QSettings:
    """Return LitExtractor settings, migrating PatentExtractor preferences on first use."""
    settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
    legacy_settings = QSettings(_LEGACY_SETTINGS_ORG, _LEGACY_SETTINGS_APP)
    _migrate_legacy_settings(settings, legacy_settings)
    return settings
