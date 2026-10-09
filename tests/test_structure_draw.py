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

"""RDKit depiction smoke test."""

from __future__ import annotations

from rdkit import Chem

from patentextractor.structure_draw import render_molecule_png


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
