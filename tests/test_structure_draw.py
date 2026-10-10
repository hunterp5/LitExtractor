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

"""RDKit depiction smoke test."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from rdkit import Chem

from litextractor.structure_draw import configure_mol_drawer, render_molecule_png


def test_render_ethanol_png():
    mol = Chem.MolFromSmiles("CCO")
    png = render_molecule_png(mol, 120, 100)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 100


def test_render_unsanitized_mol_does_not_raise():
    mol = Chem.MolFromSmiles("C(C)(C)(C)(C)C", sanitize=False)
    assert mol is not None
    png = render_molecule_png(mol, 80, 80)
    assert isinstance(png, bytes)


def test_structure_draw_import_does_not_import_qt():
    project_root = Path(__file__).resolve().parents[1]
    script = """
import importlib.abc
import sys

class BlockQtFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "PySide6" or fullname.startswith("PySide6."):
            raise AssertionError("structure_draw imported PySide6")

sys.meta_path.insert(0, BlockQtFinder())
import litextractor.structure_draw
assert not any(name == "PySide6" or name.startswith("PySide6.") for name in sys.modules)
"""
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )


def test_drawer_bond_width_tracks_layout_dimensions():
    from litextractor.structure_layout import set_structure_size, structure_height, structure_width

    old_width, old_height = structure_width(), structure_height()

    class FakeDrawer:
        def __init__(self):
            self.options = SimpleNamespace()

        def drawOptions(self):
            return self.options

    try:
        set_structure_size(100, 100, persist=False)
        drawer = FakeDrawer()
        configure_mol_drawer(drawer, target_w=200)
        assert drawer.options.bondLineWidth == 2.0
    finally:
        set_structure_size(old_width, old_height, persist=False)
