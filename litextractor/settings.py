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

"""Application settings identity."""

from __future__ import annotations

from PySide6.QtCore import QSettings

SETTINGS_ORG = "LitExtractor"
SETTINGS_APP = "LitExtractor"


def application_settings() -> QSettings:
    """Return the LitExtractor settings store."""
    return QSettings(SETTINGS_ORG, SETTINGS_APP)
