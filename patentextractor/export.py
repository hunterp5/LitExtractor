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

"""Export extracted molecules to CSV, SMILES, and SDF."""

from __future__ import annotations

import csv
from pathlib import Path

from rdkit import Chem

from .chemistry import parse_mol
from .models import ExtractedMolecule


def molecule_export_rows(molecules: list[ExtractedMolecule]) -> list[dict[str, str]]:
    """Tabular fields used by CSV export and the results table."""
    rows: list[dict[str, str]] = []
    for rec in molecules:
        rows.append(
            {
                "SMILES": rec.smiles,
                "Identifier": rec.identifier,
                "Page": "; ".join(str(page) for page in rec.page_numbers),
                "Source": "; ".join(rec.sources) if rec.sources else rec.source,
                "Score": "" if rec.score is None else f"{rec.score:.3f}",
                "Formula": rec.formula,
                "MW": "" if rec.molecular_weight is None else f"{rec.molecular_weight:.3f}",
                "InChIKey": rec.inchi_key,
                "Context": rec.context,
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
        for rec in molecules:
            if not rec.smiles:
                continue
            name = rec.identifier or rec.inchi_key or ""
            handle.write(f"{rec.smiles}\t{name}\n" if name else f"{rec.smiles}\n")


def write_sdf(path: str | Path, molecules: list[ExtractedMolecule]) -> int:
    """Write RDKit-parseable records to SDF. Returns the number of molecules written."""
    written = 0
    writer = Chem.SDWriter(str(path))
    try:
        for rec in molecules:
            mol = parse_mol(smiles=rec.smiles, molfile=rec.molfile)
            if mol is None:
                continue
            mol.SetProp("Identifier", rec.identifier)
            mol.SetProp("Page", "; ".join(str(page) for page in rec.page_numbers))
            mol.SetProp("Source", "; ".join(rec.sources) if rec.sources else rec.source)
            if rec.score is not None:
                mol.SetProp("Score", f"{rec.score:.3f}")
            if rec.formula:
                mol.SetProp("Formula", rec.formula)
            if rec.inchi_key:
                mol.SetProp("InChIKey", rec.inchi_key)
            if rec.context:
                mol.SetProp("Context", rec.context)
            writer.write(mol)
            written += 1
    finally:
        writer.close()
    return written
