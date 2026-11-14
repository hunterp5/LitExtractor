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

"""Export one extraction result as an Excel workbook.

Sheets: Molecules (with a picture of each structure and the table columns shown beside the
molecules), Table data (the long form), one sheet per table as printed (unmatched rows
included) and Reactions when there are any. Every text cell is written as text, never as a
formula: extracted values such as "=45 nM" must not be evaluated by Excel.
"""

from __future__ import annotations

import io
import logging
import re
from pathlib import Path

from .export import molecule_export_rows, shown_table_values
from .models import ExtractedMolecule, ExtractionResult
from .table_export import LONG_FIELDS, long_rows, table_rows_with_links

logger = logging.getLogger(__name__)

STRUCTURE_HEADER = "Structure"
_IMAGE_WIDTH, _IMAGE_HEIGHT = 220, 140
_STRUCTURE_ROW_HEIGHT = 108  # points; fits the 140 px picture
_MAX_CELL_CHARS = 32767  # Excel's limit for one cell
_NUMERIC_MOLECULE_FIELDS = {"Confidence", "MW"}
_SHEET_NAME_FORBIDDEN = re.compile(r"[\[\]:*?/\\]")


def _structure_png(molecule: ExtractedMolecule) -> bytes:
    """A picture of the structure, or b"" when it cannot be drawn."""
    from .chemistry import parse_mol
    from .structure_draw import render_molecule_png

    try:
        rdkit_mol = parse_mol(smiles=molecule.smiles, molfile=molecule.molfile)
        if rdkit_mol is None:
            return b""
        return render_molecule_png(rdkit_mol, _IMAGE_WIDTH, _IMAGE_HEIGHT)
    except Exception:
        logger.debug("Could not draw %r for Excel", molecule.smiles, exc_info=True)
        return b""


def _sheet_name(name: str, used: set[str]) -> str:
    """A valid, unique sheet name (at most 31 characters, none of []:*?/\\)."""
    base = _SHEET_NAME_FORBIDDEN.sub("_", name).strip("' ")[:31] or "Sheet"
    candidate, number = base, 2
    while candidate.lower() in used:
        suffix = f" ({number})"
        candidate, number = base[: 31 - len(suffix)] + suffix, number + 1
    used.add(candidate.lower())
    return candidate


class _Sheet:
    """Write rows of text and numbers to one worksheet, tracking column widths."""

    def __init__(self, workbook, name: str, headers: list[str], formats: dict) -> None:
        self.sheet = workbook.add_worksheet(name)
        self.formats = formats
        self.widths = [min(max(len(header), 8), 60) for header in headers]
        for column, header in enumerate(headers):
            self.sheet.write_string(0, column, header, formats["header"])
        self.sheet.freeze_panes(1, 0)
        self.headers = headers
        self.rows = 0

    def write_row(self, values: list[object], numeric: set[int] = frozenset()) -> int:
        self.rows += 1
        for column, value in enumerate(values):
            self._write(self.rows, column, value, column in numeric)
        return self.rows

    def _write(self, row: int, column: int, value: object, numeric: bool) -> None:
        if value is None or value == "":
            return
        if numeric:
            try:
                self.sheet.write_number(row, column, float(value), self.formats["text"])
                self._widen(column, f"{float(value):g}")
                return
            except (TypeError, ValueError):
                pass
        text = str(value)[:_MAX_CELL_CHARS]
        self.sheet.write_string(row, column, text, self.formats["text"])
        self._widen(column, text)

    def _widen(self, column: int, text: str) -> None:
        if column < len(self.widths):
            self.widths[column] = min(max(self.widths[column], len(text) + 2), 60)

    def finish(self, fixed_widths: dict[int, float] | None = None) -> None:
        for column, width in enumerate(self.widths):
            self.sheet.set_column(column, column, (fixed_widths or {}).get(column, width))
        if self.rows:
            self.sheet.autofilter(0, 0, self.rows, len(self.headers) - 1)


def write_xlsx(
    path: str | Path,
    result: ExtractionResult,
    molecules: list[ExtractedMolecule] | None = None,
    *,
    structure_images: bool = True,
) -> dict[str, int]:
    """Write *result* as an Excel workbook; return the number of rows on each sheet.

    *molecules* sets the Molecules sheet's rows and order (the order shown in the app);
    ``result.molecules`` by default.
    """
    import xlsxwriter

    molecules = list(result.molecules if molecules is None else molecules)
    workbook = xlsxwriter.Workbook(str(path), {"strings_to_formulas": False,
                                                "strings_to_urls": False})
    workbook.set_properties({"title": f"LitExtractor: {Path(result.pdf_path).name}",
                             "comments": result.pdf_path})
    formats = {
        "header": workbook.add_format({"bold": True, "bg_color": "#EEF0F4", "border": 1,
                                       "text_wrap": True, "valign": "top"}),
        "text": workbook.add_format({"valign": "top"}),
    }
    used: set[str] = set()
    counts: dict[str, int] = {}
    try:
        counts["Molecules"] = _write_molecules(
            workbook, _sheet_name("Molecules", used), result, molecules, formats,
            structure_images,
        )
        if result.tables:
            name = _sheet_name("Table data", used)
            sheet = _Sheet(workbook, name, LONG_FIELDS, formats)
            number_column = LONG_FIELDS.index("Number")
            for line in long_rows(result):
                sheet.write_row([line[field] for field in LONG_FIELDS], {number_column})
            sheet.finish()
            counts[name] = sheet.rows
        for table in result.tables:
            header, *rows = table_rows_with_links(result, table)
            name = _sheet_name(f"{table.id} {table.name}", used)
            sheet = _Sheet(workbook, name, header, formats)
            for row in rows:
                sheet.write_row(row)
            if table.title:
                sheet.sheet.write_comment(0, 0, table.title)
            sheet.finish()
            counts[name] = sheet.rows
        if result.reactions:
            name = _sheet_name("Reactions", used)
            headers = ["Page", "Reactants", "Products", "Conditions", "Source"]
            sheet = _Sheet(workbook, name, headers, formats)
            for reaction in result.reactions:
                sheet.write_row([reaction.page, " + ".join(reaction.reactants),
                                 " + ".join(reaction.products), reaction.conditions,
                                 reaction.source], {0})
            sheet.finish()
            counts[name] = sheet.rows
    finally:
        workbook.close()
    return counts


def _write_molecules(workbook, name, result, molecules, formats, structure_images) -> int:
    rows = molecule_export_rows(molecules)
    for row, molecule in zip(rows, molecules):
        row.update(shown_table_values(result, molecule))
    fields = list(rows[0]) if rows else list(molecule_export_rows(
        [ExtractedMolecule(smiles="")])[0])
    headers = ([STRUCTURE_HEADER] if structure_images else []) + fields
    offset = 1 if structure_images else 0
    numeric = {fields.index(field) + offset for field in _NUMERIC_MOLECULE_FIELDS
               if field in fields}
    sheet = _Sheet(workbook, name, headers, formats)
    for row, molecule in zip(rows, molecules):
        excel_row = sheet.write_row(([""] if structure_images else [])
                                    + [row.get(field, "") for field in fields], numeric)
        if not structure_images:
            continue
        png = _structure_png(molecule)
        if png:
            sheet.sheet.set_row(excel_row, _STRUCTURE_ROW_HEIGHT)
            sheet.sheet.insert_image(excel_row, 0, f"structure{excel_row}.png", {
                "image_data": io.BytesIO(png), "x_offset": 2, "y_offset": 2,
                "object_position": 1,
            })
    sheet.finish({0: _IMAGE_WIDTH / 7} if structure_images else None)
    return sheet.rows
