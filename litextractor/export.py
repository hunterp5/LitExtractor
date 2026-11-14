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

"""Export extracted molecules to CSV, SMILES, and SDF.

Given the extraction result, CSV and SDF exports also carry the table columns the user chose to
show beside the molecules (the "wide" form of table data). Long-form and per-table exports are
in :mod:`litextractor.table_export`.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from .models import ExtractedMolecule, ExtractionResult

logger = logging.getLogger(__name__)


def molecule_export_rows(molecules: list[ExtractedMolecule]) -> list[dict[str, str]]:
    """Tabular fields used by CSV export and the results table.

    MolDetect's detection "score" is not exported: it is the same placeholder value (2011) for
    every structure. MolScribe's confidence is the per-structure measure.
    """
    rows: list[dict[str, str]] = []
    for molecule in molecules:
        rows.append(
            {
                "SMILES": molecule.smiles,
                "Identifier": molecule.identifier,
                "Page": "; ".join(str(page) for page in molecule.page_numbers),
                "Source": "; ".join(molecule.sources) if molecule.sources else molecule.source,
                "Confidence": "" if molecule.confidence is None else f"{molecule.confidence:.3f}",
                "Low confidence": "yes" if molecule.low_confidence else "",
                "Formula": molecule.formula,
                "MW": (
                    "" if molecule.molecular_weight is None else f"{molecule.molecular_weight:.3f}"
                ),
                "InChIKey": molecule.inchi_key,
                "Context": molecule.context,
                "Figure values": "; ".join(molecule.figure_values),
            }
        )
    return rows


def shown_table_values(
    result: ExtractionResult | None, molecule: ExtractedMolecule
) -> dict[str, str]:
    """The molecule's values in the table columns shown beside it, by column header."""
    from .table_review import molecule_value, shown_column_header, table_by_id

    values: dict[str, str] = {}
    for table_id, column in result.shown_table_columns if result is not None else []:
        table = table_by_id(result, table_id)
        if table is not None:
            values[shown_column_header(table, column)] = molecule_value(
                result, table_id, column, molecule.id
            )
    return values


def write_csv(
    path: str | Path,
    molecules: list[ExtractedMolecule],
    result: ExtractionResult | None = None,
) -> None:
    """Write molecule records as UTF-8 CSV, with *result*'s shown table columns appended."""
    fieldnames = [
        "SMILES",
        "Identifier",
        "Page",
        "Source",
        "Confidence",
        "Low confidence",
        "Formula",
        "MW",
        "InChIKey",
        "Context",
        "Figure values",
    ]
    rows = molecule_export_rows(molecules)
    for row, molecule in zip(rows, molecules):
        row.update(shown_table_values(result, molecule))
    fieldnames += [header for header in (rows[0] if rows else {}) if header not in fieldnames]
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


def write_sdf(
    path: str | Path,
    molecules: list[ExtractedMolecule],
    result: ExtractionResult | None = None,
) -> int:
    """Write RDKit-parseable records to SDF. Returns the number of molecules written.

    The table columns shown beside the molecules in *result* become SDF data fields (empty
    values are left out).

    Records RDKit cannot parse or serialize (for example OCR'd aromatic rings that cannot be
    kekulized) are skipped individually so one bad structure does not abort the export.
    """
    from rdkit import Chem

    from .chemistry import parse_mol

    written = 0
    writer = Chem.SDWriter(str(path))
    try:
        for molecule in molecules:
            rdkit_mol = parse_mol(smiles=molecule.smiles, molfile=molecule.molfile)
            if rdkit_mol is None:
                continue
            _set_sdf_properties(rdkit_mol, molecule)
            for header, value in shown_table_values(result, molecule).items():
                if value:
                    rdkit_mol.SetProp(header, value)
            try:
                # A failed write emits nothing, so the file stays well-formed.
                writer.write(rdkit_mol)
            except Exception:
                logger.warning("Skipping unwritable SDF record %r", molecule.smiles, exc_info=True)
                continue
            written += 1
    finally:
        writer.close()
    return written


def _set_sdf_properties(rdkit_mol, molecule: ExtractedMolecule) -> None:
    """Copy the record's metadata onto ``rdkit_mol`` as SDF data fields."""
    rdkit_mol.SetProp("Identifier", molecule.identifier)
    rdkit_mol.SetProp("Page", "; ".join(str(page) for page in molecule.page_numbers))
    rdkit_mol.SetProp(
        "Source", "; ".join(molecule.sources) if molecule.sources else molecule.source
    )
    if molecule.confidence is not None:
        rdkit_mol.SetProp("Confidence", f"{molecule.confidence:.3f}")
        rdkit_mol.SetProp("LowConfidence", "yes" if molecule.low_confidence else "no")
    if molecule.formula:
        rdkit_mol.SetProp("Formula", molecule.formula)
    if molecule.molecular_weight is not None:
        rdkit_mol.SetProp("MW", f"{molecule.molecular_weight:.3f}")
    if molecule.inchi_key:
        rdkit_mol.SetProp("InChIKey", molecule.inchi_key)
    if molecule.context:
        rdkit_mol.SetProp("Context", molecule.context)
    if molecule.figure_values:
        rdkit_mol.SetProp("FigureValues", "\n".join(molecule.figure_values))
