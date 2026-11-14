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

"""Export table data: long (one value per line) and each table as printed.

The wide form (chosen table columns beside each molecule) is part of the molecule CSV and SDF
exports in :mod:`litextractor.export`.

Values are always exported as printed. The long form adds a parsed qualifier, number and unit
where the text is a plain measurement ("<0.1", "12 ± 3", "IC50 (nM)" header); anything else
(">10 µM in 2/3 runs", "+++") keeps an empty number, so nothing is guessed.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from .models import ExtractedMolecule, ExtractedTable, ExtractionResult, TableLink
from .table_review import RowStatus, molecule_by_id, row_links, row_status

LONG_FIELDS = [
    "Identifier",
    "SMILES",
    "InChIKey",
    "Table",
    "Table title",
    "Pages",
    "Row",
    "Row label",
    "Column",
    "Value",
    "Qualifier",
    "Number",
    "Unit",
    "Link",
]

_QUALIFIERS = {"<": "<", ">": ">", "≤": "<=", "≥": ">=", "<=": "<=", ">=": ">=",
               "~": "~", "≈": "~", "=": "="}
_MEASUREMENT = re.compile(
    r"^(?P<qualifier><=|>=|[<>≤≥~≈=])?\s*"
    r"(?P<number>[-+−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|[-+−]?\.\d+)"
    r"(?:\s*(?:±|\+/-)\s*[\d.]+)?\s*$"
)
_HEADER_UNIT = re.compile(r"[(\[]\s*([%°µμa-zA-Z][%°µμa-zA-Z0-9/·.\-]{0,11})\s*[)\]]\s*$")


def parse_value(text: str) -> tuple[str, float | None]:
    """Split a printed measurement into (qualifier, number); (``""``, None) if it is not one.

    ``"<0.1"`` gives ``("<", 0.1)``, ``"1,200"`` gives ``("", 1200.0)``, ``"12 ± 3"`` gives
    ``("", 12.0)``; ``"+++"``, ``"NT"`` and ``"2003 (FDA)"`` give ``("", None)``.
    """
    match = _MEASUREMENT.match(text.strip())
    if not match:
        return "", None
    qualifier = _QUALIFIERS.get(match.group("qualifier") or "", "")
    number = match.group("number").replace(",", "").replace("−", "-")
    return qualifier, float(number)


def header_unit(header: str) -> str:
    """The unit printed at the end of a header ("IC50 (nM)" gives "nM"), or ""."""
    match = _HEADER_UNIT.search(header)
    return match.group(1) if match else ""


def link_status_text(links: list[TableLink]) -> str:
    """Words describing a row's links, as written to the exports."""
    status = row_status(links)
    if status is RowStatus.CONFIRMED:
        return "linked by hand" if links[0].method == "manual" else "confirmed"
    if status is RowStatus.SUGGESTED:
        notes = {"ocr": " (OCR match)", "fuzzy": " (spelling differs)"}
        return "suggested" + notes.get(links[0].method, "")
    if status is RowStatus.AMBIGUOUS:
        return "ambiguous"
    return "unlinked"


def _number_text(number: float | None) -> str:
    return "" if number is None else f"{number:g}"


def long_rows(result: ExtractionResult, include_ambiguous: bool = True) -> list[dict[str, str]]:
    """One line per linked molecule, table row and non-empty column (the key column excluded).

    Rows linked to several molecules appear once per molecule with Link "ambiguous", unless
    *include_ambiguous* is False. Unlinked rows are left out: they are in the per-table export.
    Values printed under structures in figures follow (see :func:`figure_value_rows`).
    """
    lines: list[dict[str, str]] = []
    for table in result.tables:
        units = [header_unit(header) for header in table.columns]
        for row_index, row in enumerate(table.rows):
            links = row_links(result, table.id, row_index)
            status = link_status_text(links)
            if not links or (status == "ambiguous" and not include_ambiguous):
                continue
            label = row[table.key_column] if table.key_column is not None else ""
            for link in links:
                molecule = molecule_by_id(result, link.molecule_id)
                if molecule is None:
                    continue
                for column, value in enumerate(row):
                    if not value or column == table.key_column:
                        continue
                    qualifier, number = parse_value(value)
                    lines.append({
                        "Identifier": molecule.identifier,
                        "SMILES": molecule.smiles,
                        "InChIKey": molecule.inchi_key,
                        "Table": table.name,
                        "Table title": table.title,
                        "Pages": "; ".join(str(page) for page in table.pages),
                        "Row": str(row_index + 1),
                        "Row label": label or link.label,
                        "Column": table.columns[column] or f"Column {column + 1}",
                        "Value": value,
                        "Qualifier": qualifier,
                        "Number": _number_text(number),
                        "Unit": units[column] if number is not None else "",
                        "Link": status,
                    })
    lines += figure_value_rows(result.molecules)
    return lines


#: What the long export calls values printed under a structure in a figure.
FIGURE_TABLE = "Figure"


def figure_value_rows(molecules: list[ExtractedMolecule]) -> list[dict[str, str]]:
    """Long-form lines for the values printed under structures in figures.

    Table is "Figure", Table title the heading the value was printed under (such as
    "in rat: 5 mg/kg IV dose"), Column what was measured and Link "printed with structure".
    """
    from .figure_values import parse_figure_values

    lines: list[dict[str, str]] = []
    for molecule in molecules:
        for value in parse_figure_values(molecule.figure_values):
            lines.append({
                "Identifier": molecule.identifier,
                "SMILES": molecule.smiles,
                "InChIKey": molecule.inchi_key,
                "Table": FIGURE_TABLE,
                "Table title": value.heading,
                "Pages": "; ".join(str(page) for page in molecule.page_numbers),
                "Row": "",
                "Row label": molecule.identifier,
                "Column": value.name,
                "Value": value.value,
                "Qualifier": value.qualifier,
                "Number": _number_text(value.number),
                "Unit": value.unit,
                "Link": "printed with structure",
            })
    return lines


def write_long_csv(path: str | Path, result: ExtractionResult) -> int:
    """Write the long table-data CSV; return how many value lines were written."""
    lines = long_rows(result)
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LONG_FIELDS)
        writer.writeheader()
        writer.writerows(lines)
    return len(lines)


def table_rows_with_links(result: ExtractionResult, table: ExtractedTable) -> list[list[str]]:
    """The table as printed, headed by its columns, with each row's structure in front."""
    lines = [["Structure", "SMILES", "Link", *(c or f"Column {i + 1}" for i, c in
                                             enumerate(table.columns))]]
    for row_index, row in enumerate(table.rows):
        links = row_links(result, table.id, row_index)
        if row_status(links) is RowStatus.CONFIRMED:
            links = [link for link in links if link.confirmed]
        molecules = [molecule_by_id(result, link.molecule_id) for link in links]
        molecules = [molecule for molecule in molecules if molecule is not None]
        lines.append([
            "; ".join(molecule.identifier for molecule in molecules),
            "; ".join(molecule.smiles for molecule in molecules),
            link_status_text(links),
            *row,
        ])
    return lines


def table_file_name(table: ExtractedTable) -> str:
    """A file name for one table, unique within a result: "T2 Table 3.csv"."""
    name = re.sub(r"[^\w.\- ]+", "_", table.name).strip() or "Table"
    return f"{table.id} {name}.csv"


def write_table_csvs(folder: str | Path, result: ExtractionResult) -> list[Path]:
    """Write each table as printed, with its links, to its own CSV in *folder*."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for table in result.tables:
        path = folder / table_file_name(table)
        with path.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerows(table_rows_with_links(result, table))
        written.append(path)
    return written
