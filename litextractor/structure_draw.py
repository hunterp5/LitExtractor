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

"""RDKit 2D structure rendering (no Qt)."""

from __future__ import annotations

from rdkit import Chem
from rdkit.Chem.Draw import rdMolDraw2D

from .structure_dimensions import STRUCTURE_BOND_LINE_WIDTH, STRUCTURE_WIDTH


def configure_mol_drawer(drawer: rdMolDraw2D.MolDraw2D, target_width: int) -> None:
    """Thinner bonds at table resolution; scale stroke with larger depictions."""
    draw_options = drawer.drawOptions()
    base_width = float(STRUCTURE_WIDTH)
    scale_ratio = max(1.0, float(target_width) / base_width)
    draw_options.bondLineWidth = float(STRUCTURE_BOND_LINE_WIDTH) * scale_ratio


def mol_ready_for_drawing(rdkit_mol: Chem.Mol | None) -> Chem.Mol | None:
    """Return a sanitized copy that RDKit can depict, or None."""
    if rdkit_mol is None:
        return None
    try:
        mol_copy = Chem.Mol(rdkit_mol)
        Chem.SanitizeMol(mol_copy)
        return mol_copy
    except Exception:
        pass
    try:
        mol_copy = Chem.Mol(rdkit_mol)
        mol_copy.UpdatePropertyCache(strict=False)
        Chem.GetSSSR(mol_copy)
        return mol_copy
    except Exception:
        return None


def render_molecule_png(rdkit_mol: Chem.Mol, target_width: int, target_height: int) -> bytes:
    """Draw *rdkit_mol* to PNG bytes at the requested size. Empty bytes if drawing fails."""
    ready = mol_ready_for_drawing(rdkit_mol)
    if ready is None:
        return b""
    try:
        drawer = rdMolDraw2D.MolDraw2DCairo(int(target_width), int(target_height))
        configure_mol_drawer(drawer, int(target_width))
        rdMolDraw2D.PrepareAndDrawMolecule(drawer, ready)
        drawer.FinishDrawing()
        return drawer.GetDrawingText()
    except Exception:
        return b""
