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

"""Tests for the Help citation guide."""

from __future__ import annotations


def test_citation_dialog_covers_core_stack_and_links(qapp):  # noqa: ARG001
    from litextractor.ui.dialogs.citations import CitationsDialog

    dialog = CitationsDialog()
    html = dialog._browser.toHtml()

    for technology in ("LitExtractor", "PySide6", "PyTorch", "RDKit", "OpenChemIE"):
        assert technology in html
    assert "10.1021/acs.jcim.4c00572" in html
    assert "10.1145/3620665.3640366" in html
    assert dialog._browser.openExternalLinks()
    dialog.close()


def test_help_citations_action_opens_the_dialog(qapp, monkeypatch):  # noqa: ARG001
    import litextractor.ui.main_window as main_window

    opened: list[bool] = []

    class FakeCitationsDialog:
        def __init__(self, _parent):
            pass

        def exec(self):
            opened.append(True)

    monkeypatch.setattr(main_window, "CitationsDialog", FakeCitationsDialog)
    window = main_window.MainWindow()
    help_menu = window._help_menu
    citations_action = next(action for action in help_menu.actions() if action.text() == "&Citations")

    citations_action.trigger()

    assert opened == [True]
    window.close()
