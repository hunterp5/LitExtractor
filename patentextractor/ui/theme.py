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

"""Application-wide, persistent Qt themes."""

from __future__ import annotations

import ctypes
import colorsys
import random
import sys

from PySide6.QtCore import QEvent, QObject, QSettings
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QWidget

THEME_LIGHT = "light"
THEME_DARK = "dark"
THEME_GROOVY = "groovy"
THEME_NAMES = (THEME_LIGHT, THEME_DARK, THEME_GROOVY)

_SETTINGS_ORG = "PatentExtractor"
_SETTINGS_APP = "PatentExtractor"
_SETTINGS_KEY_THEME = "gui/theme"
_SETTINGS_KEY_TABLE_FONT_PT = "gui/table_font_pt"
_SETTINGS_KEY_APP_FONT_PT = "gui/app_font_pt"

_CURRENT_THEME = THEME_LIGHT
_FONT_THEME_FILTER: _ThemeWindowFilter | None = None

MIN_FONT_PT = 8
MAX_FONT_PT = 32
DEFAULT_FONT_PT = 10
# Backwards-compatible aliases (table-specific names used elsewhere).
MIN_TABLE_FONT_PT = MIN_FONT_PT
MAX_TABLE_FONT_PT = MAX_FONT_PT


def current_theme_name() -> str:
    """Return the normalized theme currently applied to the application."""
    return _CURRENT_THEME


def _normalize_theme_name(theme: str | None) -> str:
    """Normalize stored values into the closed set of supported theme names."""
    name = str(theme or "").strip().lower().replace("-", "_")
    aliases = {
        "light": THEME_LIGHT,
        "light_mode": THEME_LIGHT,
        "dark": THEME_DARK,
        "dark_mode": THEME_DARK,
        "groovy": THEME_GROOVY,
        "groovy_mode": THEME_GROOVY,
        "psychedelic": THEME_GROOVY,
    }
    return aliases.get(name, THEME_LIGHT)


def load_saved_theme_name() -> str:
    """Return the user's saved theme; default to Light for new or legacy settings."""
    settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    stored = settings.value(_SETTINGS_KEY_THEME, "")
    name = _normalize_theme_name(str(stored or ""))
    if stored != name:
        settings.setValue(_SETTINGS_KEY_THEME, name)
        settings.sync()
    return name


def save_theme_name(theme: str) -> None:
    """Persist a theme selection after normalizing it to the supported three."""
    settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    settings.setValue(_SETTINGS_KEY_THEME, _normalize_theme_name(theme))
    settings.sync()


def _clamp_font_pt(pt: int) -> int:
    return max(MIN_FONT_PT, min(MAX_FONT_PT, int(pt)))


def default_app_font_pt() -> int:
    """Default application-wide font point size."""
    return DEFAULT_FONT_PT


def default_table_font_pt() -> int:
    """Default table font size (matches the application default)."""
    return DEFAULT_FONT_PT


def _load_saved_font_pt(key: str) -> int:
    raw = QSettings(_SETTINGS_ORG, _SETTINGS_APP).value(key, 0)
    try:
        pt = int(str(raw))
    except (TypeError, ValueError):
        pt = 0
    if pt <= 0:
        return default_app_font_pt()
    return _clamp_font_pt(pt)


def load_saved_table_font_pt() -> int:
    """Saved table font point size, clamped to the supported range (default when unset)."""
    return _load_saved_font_pt(_SETTINGS_KEY_TABLE_FONT_PT)


def save_table_font_pt(pt: int) -> None:
    QSettings(_SETTINGS_ORG, _SETTINGS_APP).setValue(_SETTINGS_KEY_TABLE_FONT_PT, int(pt))


def load_saved_app_font_pt() -> int:
    """Saved application-wide font point size, clamped (default when unset)."""
    return _load_saved_font_pt(_SETTINGS_KEY_APP_FONT_PT)


def save_app_font_pt(pt: int) -> None:
    QSettings(_SETTINGS_ORG, _SETTINGS_APP).setValue(_SETTINGS_KEY_APP_FONT_PT, int(pt))


def apply_application_font_pt(pt: int) -> int:
    """Set the application-wide font point size; returns the clamped size applied."""
    app = QApplication.instance()
    pt = _clamp_font_pt(pt)
    if isinstance(app, QApplication):
        font = QFont(app.font())
        font.setPointSize(pt)
        app.setFont(font)
    return pt


def _light_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#f5f7fa"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#19202c"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#eef0f4"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#141414"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#19202c"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#eceff4"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#19202c"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#2e67c8"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#4077f4"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Mid, QColor("#b7bec7"))
    palette.setColor(QPalette.ColorRole.Dark, QColor("#767e88"))
    palette.setColor(QPalette.ColorRole.Light, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Shadow, QColor("#3f4954"))
    disabled = QColor("#949ca8")
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled)
    return palette


def _dark_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#25272b"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#f0f0f0"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#191a1d"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#2d3035"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#35383e"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#f0f0f0"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#f0f0f0"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#3a3d43"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#f0f0f0"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#8ab4ff"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#477bd1"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Mid, QColor("#666b74"))
    palette.setColor(QPalette.ColorRole.Dark, QColor("#17191c"))
    palette.setColor(QPalette.ColorRole.Light, QColor("#4a4e55"))
    palette.setColor(QPalette.ColorRole.Shadow, QColor("#101114"))
    disabled = QColor("#8b9099")
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled)
    return palette


def _hsv_qcolor(hue: float, saturation: float, value: float) -> QColor:
    red, green, blue = colorsys.hsv_to_rgb(
        hue % 1.0,
        max(0.0, min(1.0, saturation)),
        max(0.0, min(1.0, value)),
    )
    return QColor(int(red * 255), int(green * 255), int(blue * 255))


def _contrasting_text(background: QColor) -> QColor:
    """Choose a readable foreground using the background's approximate luminance."""
    luminance = (
        0.2126 * background.red() + 0.7152 * background.green() + 0.0722 * background.blue()
    ) / 255.0
    return QColor(18, 18, 22) if luminance > 0.55 else QColor(250, 248, 255)


def _groovy_palette(rng: random.Random | None = None) -> QPalette:
    """Build a randomized multi-hue Groovy palette with contrasting text."""
    rng = rng or random.Random()
    base_hue = rng.random()

    def shifted_color(
        offset: float,
        saturation: tuple[float, float],
        value: tuple[float, float],
    ) -> QColor:
        return _hsv_qcolor(
            base_hue + offset,
            rng.uniform(*saturation),
            rng.uniform(*value),
        )

    window = shifted_color(0.00, (0.55, 0.95), (0.35, 0.75))
    base = shifted_color(0.12, (0.45, 0.90), (0.22, 0.55))
    alternate = shifted_color(0.22, (0.50, 0.95), (0.30, 0.65))
    button = shifted_color(0.35, (0.60, 1.00), (0.40, 0.85))
    highlight = shifted_color(0.55, (0.75, 1.00), (0.55, 0.95))
    link = shifted_color(0.70, (0.70, 1.00), (0.55, 0.95))
    mid = shifted_color(0.08, (0.25, 0.55), (0.35, 0.60))
    light = shifted_color(0.05, (0.35, 0.70), (0.70, 0.95))
    dark = shifted_color(0.02, (0.40, 0.80), (0.12, 0.30))
    tooltip = shifted_color(0.40, (0.50, 0.90), (0.35, 0.70))

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, window)
    palette.setColor(QPalette.ColorRole.WindowText, _contrasting_text(window))
    palette.setColor(QPalette.ColorRole.Base, base)
    palette.setColor(QPalette.ColorRole.AlternateBase, alternate)
    palette.setColor(QPalette.ColorRole.ToolTipBase, tooltip)
    palette.setColor(QPalette.ColorRole.ToolTipText, _contrasting_text(tooltip))
    palette.setColor(QPalette.ColorRole.Text, _contrasting_text(base))
    palette.setColor(QPalette.ColorRole.Button, button)
    palette.setColor(QPalette.ColorRole.ButtonText, _contrasting_text(button))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffff50"))
    palette.setColor(QPalette.ColorRole.Link, link)
    palette.setColor(QPalette.ColorRole.Highlight, highlight)
    palette.setColor(QPalette.ColorRole.HighlightedText, _contrasting_text(highlight))
    palette.setColor(QPalette.ColorRole.Mid, mid)
    palette.setColor(QPalette.ColorRole.Dark, dark)
    palette.setColor(QPalette.ColorRole.Light, light)
    palette.setColor(QPalette.ColorRole.Shadow, QColor("#0a0514"))
    disabled = QColor(mid.red(), mid.green(), mid.blue(), 160)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled)
    return palette


def palette_for_theme(theme: str, *, rng: random.Random | None = None) -> QPalette:
    """Return the palette for *theme*; Groovy is freshly randomized on every application."""
    name = _normalize_theme_name(theme)
    if name == THEME_DARK:
        return _dark_palette()
    if name == THEME_GROOVY:
        return _groovy_palette(rng)
    return _light_palette()


def extract_panel_stylesheet() -> str:
    """Palette-driven styling for the extraction side panel."""
    return """
    QFrame#ExtractPanel {
        background-color: palette(window);
        border-right: 1px solid palette(mid);
    }
    """


def detail_panel_stylesheet() -> str:
    """Palette-driven styling for the detail side panel and its cards."""
    return """
    QFrame#DetailPanel {
        background-color: palette(window);
        border-left: 1px solid palette(mid);
    }
    QFrame#DetailCard {
        background-color: palette(base);
        border: 1px solid palette(mid);
        border-radius: 8px;
    }
    QLabel#DetailCardTitle {
        color: palette(windowtext);
        font-weight: 600;
    }
    QLabel#DetailFieldName {
        color: palette(mid);
    }
    QLabel#DetailFieldValue {
        color: palette(windowtext);
    }
    QLabel#CropPreview {
        background-color: palette(alternate-base);
        border-radius: 6px;
    }
    """


class _ThemeWindowFilter(QObject):
    """Apply the application palette to app-owned top-level windows before they show."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.Show
            and isinstance(watched, QWidget)
            and watched.isWindow()
        ):
            palette = QApplication.palette()
            watched.setPalette(palette)
            _apply_native_window_chrome(watched, palette)
        return False


def _install_window_theme_filter(app: QApplication) -> None:
    global _FONT_THEME_FILTER
    if _FONT_THEME_FILTER is None:
        _FONT_THEME_FILTER = _ThemeWindowFilter(app)
    app.installEventFilter(_FONT_THEME_FILTER)


def _apply_native_window_chrome(window: QWidget, palette: QPalette) -> None:
    """Best-effort Windows caption colors; other platforms own their decorations."""
    if sys.platform != "win32":
        return
    try:
        handle = int(window.winId())
        dark_mode = ctypes.c_int(int(_CURRENT_THEME != THEME_LIGHT))
        caption = palette.color(QPalette.ColorRole.Window)
        text = palette.color(QPalette.ColorRole.WindowText)
        caption_color = ctypes.c_int(caption.red() | caption.green() << 8 | caption.blue() << 16)
        text_color = ctypes.c_int(text.red() | text.green() << 8 | text.blue() << 16)
        dwmapi = getattr(ctypes, "windll").dwmapi
        set_attribute = dwmapi.DwmSetWindowAttribute
        set_attribute.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_uint,
        ]
        set_attribute.restype = ctypes.c_long

        def apply_attribute(attribute: int, value: ctypes.c_int) -> bool:
            result = set_attribute(
                ctypes.c_void_p(handle),
                attribute,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
            return result == 0

        if not apply_attribute(20, dark_mode):
            apply_attribute(19, dark_mode)  # Windows 10's earlier attribute value.
        apply_attribute(35, caption_color)
        apply_attribute(36, text_color)
    except Exception:
        # Native decorations are not uniformly themeable across Windows versions.
        return


def refresh_open_windows_theme(app: QApplication | None = None) -> None:
    """Refresh existing top-level windows and any optional widget theme hooks."""
    if app is None:
        instance = QApplication.instance()
        if not isinstance(instance, QApplication):
            return
        app = instance
    palette = app.palette()
    for window in app.topLevelWidgets():
        try:
            window.setPalette(palette)
            _apply_native_window_chrome(window, palette)
            refresh = getattr(window, "refresh_theme", None)
            if callable(refresh):
                refresh()
            style = window.style()
            if style is not None:
                style.unpolish(window)
                style.polish(window)
            window.update()
        except RuntimeError:
            # A widget can be deleted between the top-level snapshot and refresh.
            continue


def initialize_application_theme(app: QApplication | None = None) -> str:
    """Load and apply the persisted theme before any application windows are created."""
    return apply_application_theme(app, load_saved_theme_name())


def apply_application_theme(app: QApplication | None, theme: str) -> str:
    """Apply one normalized theme to the application and its existing/future windows."""
    global _CURRENT_THEME
    name = _normalize_theme_name(theme)
    _CURRENT_THEME = name
    if app is None:
        return name
    app.setStyle("Fusion")
    app.setPalette(palette_for_theme(name))
    _install_window_theme_filter(app)
    refresh_open_windows_theme(app)
    return name
