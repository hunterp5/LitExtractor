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

"""Export extracted molecules to CSV, SMILES, and SDF."""

from __future__ import annotations

import csv
from pathlib import Path

from .models import ExtractedMolecule


def molecule_export_rows(molecules: list[ExtractedMolecule]) -> list[dict[str, str]]:
    """Tabular fields used by CSV export and the results table."""
    rows: list[dict[str, str]] = []
    for molecule in molecules:
        rows.append(
            {
                "SMILES": molecule.smiles,
                "Identifier": molecule.identifier,
                "Page": "; ".join(str(page) for page in molecule.page_numbers),
                "Source": "; ".join(molecule.sources) if molecule.sources else molecule.source,
                "Score": "" if molecule.score is None else f"{molecule.score:.3f}",
                "Formula": molecule.formula,
                "MW": (
                    "" if molecule.molecular_weight is None else f"{molecule.molecular_weight:.3f}"
                ),
                "InChIKey": molecule.inchi_key,
                "Context": molecule.context,
            }
        )
    return rows


def write_csv(path: str | Path, molecules: list[ExtractedMolecule]) -> None:
    """Write molecule records as UTF-8 CSV."""
    fieldnames = [
        "SMILES",
        "Identifier",
        "Page",
        "Source",
        "Score",
        "Formula",
        "MW",
        "InChIKey",
        "Context",
    ]
    rows = molecule_export_rows(molecules)
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_smi(path: str | Path, molecules: list[ExtractedMolecule]) -> None:
    """Write SMILES plus identifier (tab-separated)."""
    with Path(path).open("w", encoding="utf-8", newline="\n") as handle:
        for molecule in molecules:
            if not molecule.smiles:
                continue
            name = molecule.identifier or molecule.inchi_key or ""
            handle.write(f"{molecule.smiles}\t{name}\n" if name else f"{molecule.smiles}\n")


def write_sdf(path: str | Path, molecules: list[ExtractedMolecule]) -> int:
    """Write RDKit-parseable records to SDF. Returns the number of molecules written."""
    from rdkit import Chem

    from .chemistry import parse_mol

    written = 0
    writer = Chem.SDWriter(str(path))
    try:
        for molecule in molecules:
            rdkit_mol = parse_mol(smiles=molecule.smiles, molfile=molecule.molfile)
            if rdkit_mol is None:
                continue
            rdkit_mol.SetProp("Identifier", molecule.identifier)
            rdkit_mol.SetProp("Page", "; ".join(str(page) for page in molecule.page_numbers))
            rdkit_mol.SetProp(
                "Source", "; ".join(molecule.sources) if molecule.sources else molecule.source
            )
            if molecule.score is not None:
                rdkit_mol.SetProp("Score", f"{molecule.score:.3f}")
            if molecule.formula:
                rdkit_mol.SetProp("Formula", molecule.formula)
            if molecule.inchi_key:
                rdkit_mol.SetProp("InChIKey", molecule.inchi_key)
            if molecule.context:
                rdkit_mol.SetProp("Context", molecule.context)
            writer.write(rdkit_mol)
            written += 1
    finally:
        writer.close()
    return written
