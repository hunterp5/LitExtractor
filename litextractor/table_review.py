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

"""Reviewing table rows against structures: what the Tables tab reads and changes.

Every change goes through these functions, so the result's links stay consistent: a row is
unlinked, has suggested links (one, or several marked ambiguous), or has one confirmed link.
Confirming or linking by hand settles a row; re-suggesting after an edit leaves settled rows
alone.
"""

from __future__ import annotations

from enum import Enum

from .models import ExtractedMolecule, ExtractedTable, ExtractionResult, TableLink
from .tables import row_keys, suggest_links


class RowStatus(Enum):
    """How far a table row has been matched to a structure."""

    UNLINKED = "unlinked"
    SUGGESTED = "suggested"
    AMBIGUOUS = "ambiguous"
    CONFIRMED = "confirmed"


def table_by_id(result: ExtractionResult, table_id: str) -> ExtractedTable | None:
    """Return the table with *table_id*, or None."""
    return next((table for table in result.tables if table.id == table_id), None)


def molecule_by_id(result: ExtractionResult, molecule_id: str) -> ExtractedMolecule | None:
    """Return the molecule with *molecule_id*, or None."""
    return next((molecule for molecule in result.molecules if molecule.id == molecule_id), None)


def row_links(result: ExtractionResult, table_id: str, row_index: int) -> list[TableLink]:
    """The links of one table row."""
    return [
        link
        for link in result.table_links
        if link.table_id == table_id and link.row_index == row_index
    ]


def row_status(links: list[TableLink]) -> RowStatus:
    """Classify a row by its links.

    Several links that are not ambiguous are copies of one compound drawn more than once.
    """
    if not links:
        return RowStatus.UNLINKED
    if any(link.confirmed for link in links):
        return RowStatus.CONFIRMED
    if any(link.ambiguous for link in links):
        return RowStatus.AMBIGUOUS
    return RowStatus.SUGGESTED


def link_counts(result: ExtractionResult, table: ExtractedTable) -> tuple[int, int]:
    """Return (rows with a single or confirmed link, rows) for *table*."""
    linked = sum(
        row_status(row_links(result, table.id, row)) in (RowStatus.SUGGESTED, RowStatus.CONFIRMED)
        for row in range(len(table.rows))
    )
    return linked, len(table.rows)


def molecule_rows(
    result: ExtractionResult, molecule_id: str
) -> list[tuple[ExtractedTable, int, TableLink]]:
    """Every table row linked to a molecule, in table and row order."""
    tables = {table.id: table for table in result.tables}
    order = {table.id: position for position, table in enumerate(result.tables)}
    found = [
        (tables[link.table_id], link.row_index, link)
        for link in result.table_links
        if link.molecule_id == molecule_id and link.table_id in tables
    ]
    return sorted(found, key=lambda item: (order[item[0].id], item[1]))


def _replace_row_links(
    result: ExtractionResult, table_id: str, row_index: int, links: list[TableLink]
) -> None:
    result.table_links = [
        link
        for link in result.table_links
        if not (link.table_id == table_id and link.row_index == row_index)
    ] + links


def confirm_link(
    result: ExtractionResult, table_id: str, row_index: int, molecule_id: str
) -> None:
    """Accept a row's suggested link to *molecule_id*.

    When the row is ambiguous, the other candidates are dropped. When its links are copies of
    one compound, they are all confirmed.
    """
    links = row_links(result, table_id, row_index)
    if links and not any(link.ambiguous for link in links) and any(
        link.molecule_id == molecule_id for link in links
    ):
        for link in links:
            link.confirmed = True
        return
    for link in links:
        if link.molecule_id == molecule_id:
            link.confirmed, link.ambiguous = True, False
            _replace_row_links(result, table_id, row_index, [link])
            return
    link_manually(result, table_id, row_index, molecule_id)


def link_manually(
    result: ExtractionResult, table_id: str, row_index: int, molecule_id: str
) -> TableLink:
    """Link a row to a molecule chosen by the user, replacing the row's other links."""
    table = table_by_id(result, table_id)
    keys = row_keys(table) if table is not None else []
    link = TableLink(
        table_id=table_id,
        row_index=row_index,
        molecule_id=molecule_id,
        label=keys[row_index] if row_index < len(keys) else "",
        method="manual",
        confirmed=True,
    )
    _replace_row_links(result, table_id, row_index, [link])
    return link


def unlink_row(result: ExtractionResult, table_id: str, row_index: int) -> None:
    """Remove every link of a row. It stays unlinked until its key cell is edited."""
    _replace_row_links(result, table_id, row_index, [])


def _settled_rows(result: ExtractionResult, table_id: str) -> set[int]:
    return {
        link.row_index
        for link in result.table_links
        if link.table_id == table_id and link.confirmed
    }


def resuggest_rows(result: ExtractionResult, table: ExtractedTable, rows: set[int]) -> None:
    """Replace the suggested links of *rows* with fresh ones; confirmed rows are kept."""
    rows = rows - _settled_rows(result, table.id)
    result.table_links = [
        link
        for link in result.table_links
        if not (link.table_id == table.id and link.row_index in rows)
    ] + suggest_links(table, result.molecules, rows)


def edit_cell(
    result: ExtractionResult, table: ExtractedTable, row_index: int, column: int, text: str
) -> None:
    """Correct one cell. Editing a key cell re-suggests links for the rows that use it."""
    table.rows[row_index][column] = text
    if column != table.key_column:
        return
    affected = {row_index}
    following = row_index + 1
    while following < len(table.rows) and not table.rows[following][column]:
        affected.add(following)
        following += 1
    resuggest_rows(result, table, affected)


def set_key_column(result: ExtractionResult, table: ExtractedTable, column: int | None) -> None:
    """Match the table's rows by another column, re-suggesting every unconfirmed row."""
    table.key_column = column
    resuggest_rows(result, table, set(range(len(table.rows))))


def shown_column_header(table: ExtractedTable, column: int) -> str:
    """Header of a table column shown on the molecule table, e.g. "Table 3 · IC50 (nM)"."""
    header = table.columns[column] if column < len(table.columns) else ""
    return f"{table.name} · {header or f'column {column + 1}'}"


def toggle_shown_column(result: ExtractionResult, table_id: str, column: int) -> bool:
    """Show or hide a table column beside the molecules; return whether it is now shown."""
    key = (table_id, column)
    if key in result.shown_table_columns:
        result.shown_table_columns.remove(key)
        return False
    result.shown_table_columns.append(key)
    return True


def molecule_value(
    result: ExtractionResult, table_id: str, column: int, molecule_id: str
) -> str:
    """The molecule's value in one table column, from its linked rows; "" when none.

    Rows whose link is ambiguous are left out until the user confirms one. Several rows
    (a compound tested twice) give their distinct values joined by "; ".
    """
    table = table_by_id(result, table_id)
    if table is None or column >= len(table.columns):
        return ""
    values: list[str] = []
    for _table, row_index, link in molecule_rows(result, molecule_id):
        if _table.id != table_id or (link.ambiguous and not link.confirmed):
            continue
        value = table.rows[row_index][column]
        if value and value not in values:
            values.append(value)
    return "; ".join(values)
