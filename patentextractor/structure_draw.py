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

"""RDKit 2D structure rendering (no Qt)."""

from __future__ import annotations

from rdkit import Chem
from rdkit.Chem.Draw import rdMolDraw2D

from .structure_dimensions import STRUCTURE_BOND_LINE_WIDTH, structure_width


def configure_mol_drawer(drawer: rdMolDraw2D.MolDraw2D, target_w: int) -> None:
    """Thinner bonds at table resolution; scale stroke with larger depictions."""
    opts = drawer.drawOptions()
    base_w = max(1.0, float(structure_width()))
    ratio = max(1.0, float(target_w) / base_w)
    opts.bondLineWidth = float(STRUCTURE_BOND_LINE_WIDTH) * ratio


def mol_ready_for_drawing(mol: Chem.Mol | None) -> Chem.Mol | None:
    """Return a sanitized copy that RDKit can depict, or None."""
    if mol is None:
        return None
    try:
        copy = Chem.Mol(mol)
        Chem.SanitizeMol(copy)
        return copy
    except Exception:
        pass
    try:
        copy = Chem.Mol(mol)
        copy.UpdatePropertyCache(strict=False)
        Chem.GetSSSR(copy)
        return copy
    except Exception:
        return None


def render_molecule_png(mol: Chem.Mol, target_w: int, target_h: int) -> bytes:
    """Draw *mol* to PNG bytes at the requested size. Empty bytes if drawing fails."""
    ready = mol_ready_for_drawing(mol)
    if ready is None:
        return b""
    try:
        drawer = rdMolDraw2D.MolDraw2DCairo(int(target_w), int(target_h))
        configure_mol_drawer(drawer, int(target_w))
        rdMolDraw2D.PrepareAndDrawMolecule(drawer, ready)
        drawer.FinishDrawing()
        return drawer.GetDrawingText()
    except Exception:
        return b""
