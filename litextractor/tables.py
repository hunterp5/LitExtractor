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

"""Turn OpenChemIE's raw tables into clean tables and link their rows to molecules.

OpenChemIE groups the PDF text inside each layout-detected table into rows and columns. On
real papers and patents that output needs repair before it is usable:

- Reference lists and figure panels are also detected as tables; they are dropped.
- Patents print long tables as side-by-side panels ("Ex No | IC50 | Ex No | IC50 | ...") and
  across several pages whose headers are missing; panels are unstacked and pages joined.
- Header cells merge ("Ex No  CDK12/CycK"), a second header line arrives as a data row, and
  empty cells are inserted where none are printed; these are undone.
- Ligatures ("Geﬁtinib") and other compatibility characters are normalized.

Rows are then linked to molecules by their compound label or name. A row matching several
molecules is marked ambiguous rather than resolved, and every link starts unconfirmed.
"""

from __future__ import annotations

import io
import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .models import ExtractedMolecule, ExtractedTable, TableLink

logger = logging.getLogger(__name__)

_KEY_HEADER = re.compile(
    r"^(?:ex(?:ample)?s?\.?|compo?u?n?d?s?\.?|cmpd\.?|cpd\.?|entry|drugs?|inhibitors?|"
    r"(?:compound|drug|generic)?\s*names?(?:\s*\(.*\))?|id|no\.?|#)"
    r"(?:\s*(?:no\.?|#|number|id))?$",
    re.IGNORECASE,
)
_VALUE = re.compile(
    r"^(?:[<>≤≥~=±]?\s*-?\d+(?:[.,]\d+)?\s*%?|[+\-−]{1,5}|n\.?\s?[dat]\.?|nd|na|\d+[a-z]{0,2})$",
    re.IGNORECASE,
)
_INTEGER = re.compile(r"^\d+[a-z]?$", re.IGNORECASE)
_CITATION = re.compile(
    r"\[CrossRef\]|\[PubMed\]|\bet al\.|\bdoi\b|\b(?:19|20)\d\d[,;]\s*\d+", re.IGNORECASE
)
_LABEL_PREFIX = re.compile(
    r"^(?:compound|cmpd|cpd|example|ex)\.?\s*(?:no\.?|#)?\s*(?=[\d(\[])", re.IGNORECASE
)
_OCR_FOLD = str.maketrans({"I": "1", "l": "1", "|": "1", "i": "1", "O": "0", "o": "0"})
_SHORT_LABEL = 6


def normalize_text(text: Any) -> str:
    """Return cell text with ligatures and compatibility characters normalized and spaces collapsed."""
    if text is None:
        return ""
    if isinstance(text, dict):
        text = text.get("text", "")
    return " ".join(unicodedata.normalize("NFKC", str(text)).split())


def normalize_label(label: str) -> str:
    """Normalize a compound label or name for matching.

    Case, spaces, enclosing brackets, trailing punctuation and prefixes such as "Compound" or
    "Ex." are ignored, so "Compound (12a)", "12A" and "12a." are equal.
    """
    text = normalize_text(label)
    text = _LABEL_PREFIX.sub("", text)
    text = re.sub(r"\s+", "", text).casefold().rstrip(".:,;*")
    while len(text) >= 2 and text[0] in "([{" and text[-1] in ")]}":
        text = text[1:-1]
    return text


def ocr_folded(label: str) -> str:
    """Fold characters OCR commonly confuses (I/l/i/| with 1, O/o with 0) in a short label."""
    return normalize_label(label).translate(_OCR_FOLD)


def _label_variants(text: str) -> set[str]:
    """The normalized label, plus the part before a parenthesis ("Gefitinib (Iressa)")."""
    variants = {normalize_label(text)}
    head = text.split("(", 1)[0]
    if head.strip() and head != text:
        variants.add(normalize_label(head))
    variants.discard("")
    return variants


# --------------------------------------------------------------------------- cleaning


@dataclass
class _Fragment:
    """One table as OpenChemIE returned it for one page, after cell-level cleanup."""

    page: int
    title: str
    footnote: str
    header: list[str] | None
    rows: list[list[str]]
    crop_png: bytes | None
    width: int = 0


@dataclass
class _Building:
    """A table being assembled from one or more fragments."""

    title: str
    pages: list[int]
    raw_header: list[str] | None
    width: int
    columns: list[str]
    rows: list[list[str]]
    footnote: str
    crops_png: list[bytes] = field(default_factory=list)


def _is_value(cell: str) -> bool:
    return bool(_VALUE.match(cell))


def _header_is_data(header: list[str]) -> bool:
    """True when a "header" is really a data row (a continuation page lost its header)."""
    filled = [cell for cell in header if cell]
    return bool(filled) and sum(_is_value(cell) for cell in filled) >= max(1, len(filled) / 2)


def _split_header(cells: list[Any]) -> list[str]:
    """Split header cells merged across columns ("Ex No  CDK12/CycK") at runs of 2+ spaces."""
    header: list[str] = []
    for raw in _raw_cells(cells):
        parts = [normalize_text(part) for part in re.split(r"\s{2,}", raw.strip())]
        parts = [part for part in parts if part]
        header.extend(parts or [""])
    return header


def _looks_like_references(header: list[str] | None, rows: list[list[str]]) -> bool:
    """True for a reference list: most lines cite a journal or start with a reference number."""
    lines = [" ".join(row) for row in rows] + ([" ".join(header)] if header else [])
    if not lines:
        return False
    citing = sum(bool(_CITATION.search(line)) for line in lines)
    numbered = sum(bool(re.match(r"^\d{1,3}\.\s", line)) for line in lines)
    return citing >= 0.3 * len(lines) or numbered >= 0.4 * len(lines)


def _fit_row(row: list[str], width: int) -> list[str]:
    """Make *row* exactly *width* cells long, dropping spurious empty cells first."""
    if len(row) > width:
        surplus = len(row) - width
        fitted = []
        for cell in row:
            if not cell and surplus:
                surplus -= 1
                continue
            fitted.append(cell)
        row = fitted
    if len(row) > width:
        row = row[: width - 1] + [" ".join(cell for cell in row[width - 1 :] if cell)]
    return row + [""] * (width - len(row))


def _fragment_from_openchemie(raw: dict, page: int, title: str, footnote: str) -> _Fragment | None:
    """Clean one OpenChemIE table; None when it is not a usable data table."""
    content = (raw.get("table") or {}).get("content")
    if not isinstance(content, dict):
        return None
    header = _split_header(content.get("columns") or [])
    rows = [[normalize_text(cell) for cell in row] for row in content.get("rows") or []]
    rows = [row for row in rows if any(row)]
    if header and _header_is_data(header):
        rows.insert(0, [normalize_text(cell) for cell in _raw_cells(content.get("columns"))])
        header = None
    if not header or not any(header):
        header = None
    if not re.match(r"\s*table\b", title, re.IGNORECASE) and _looks_like_references(header, rows):
        return None

    # A second header line ("+DDB1" under "CDK12/CycK") arrives as the first data row: a row
    # with no values in a table whose other rows have them.
    subheader: list[str] = []
    if (
        header is not None
        and len(rows) > 1
        and not any(_is_value(cell) for cell in rows[0] if cell)
        and any(_is_value(cell) for row in rows[1:] for cell in row if cell)
    ):
        subheader = [cell for cell in rows.pop(0) if cell]

    filled_counts = Counter(sum(bool(cell) for cell in row) for row in rows)
    width = len(header) if header else (filled_counts.most_common(1)[0][0] if rows else 0)
    if width < 2 or not rows:
        return None
    rows = [_fit_row(row, width) for row in rows]
    if header is not None and subheader:
        header = _apply_subheader(header, subheader)

    image = (raw.get("figure") or {}).get("image")
    return _Fragment(page, title, footnote, header, rows, _png_bytes(image), width)


def _raw_cells(cells: Any) -> list[str]:
    return [cell.get("text", "") if isinstance(cell, dict) else str(cell or "") for cell in cells or []]


def _apply_subheader(header: list[str], subheader: list[str]) -> list[str]:
    """Join a second header line ("+DDB1", "Degradation") onto the value columns it belongs to."""
    value_columns = [i for i, cell in enumerate(header) if not _KEY_HEADER.match(cell)]
    if len(subheader) == len(header):
        targets = list(range(len(header)))
    elif len(subheader) == len(value_columns):
        targets = value_columns
    else:
        return header
    header = list(header)
    for index, text in zip(targets, subheader):
        header[index] = f"{header[index]} {text}".strip()
    return header


def _png_bytes(image: Any) -> bytes | None:
    if image is None:
        return None
    try:
        from PIL import Image

        if not isinstance(image, Image.Image):
            import numpy as np

            image = Image.fromarray(np.asarray(image))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception:
        logger.debug("Could not encode a table image", exc_info=True)
        return None


def _column_kind(rows: list[list[str]], column: int) -> str:
    """Classify a column as "id" (labels such as 12 or 12a), "value", "text" or "empty"."""
    cells = [row[column] for row in rows if row[column]]
    if not cells:
        return "empty"
    if sum(bool(_INTEGER.match(cell)) for cell in cells) >= 0.8 * len(cells):
        return "id"
    if sum(_is_value(cell) for cell in cells) >= 0.8 * len(cells):
        return "value"
    return "text"


def _panel_width(header: list[str] | None, rows: list[list[str]], width: int) -> int:
    """Width of one panel when the table repeats its columns side by side, else *width*."""
    for size in range(1, width // 2 + 1):
        if width % size:
            continue
        if header is not None and all(header):
            keys = [cell.casefold() for cell in header]
            if all(keys[i] == keys[i % size] for i in range(width)):
                return size
        elif header is None and size >= 2:
            kinds = [_column_kind(rows, column) for column in range(width)]
            if kinds[0] == "id" and all(
                kinds[i] == kinds[i % size] or "empty" in (kinds[i], kinds[i % size])
                for i in range(width)
            ):
                return size
    return width


def _unstack(header: list[str] | None, rows: list[list[str]], width: int) -> tuple[list[str], list[list[str]]]:
    """Split side-by-side panels into one long table, panel by panel."""
    size = _panel_width(header, rows, width)
    columns = list(header[:size]) if header else [""] * size
    if size == width:
        return columns, rows
    unstacked = []
    for start in range(0, width, size):
        for row in rows:
            chunk = row[start : start + size]
            if any(chunk):
                unstacked.append(chunk)
    return columns, unstacked


def _continues(table: _Building, fragment: _Fragment) -> bool:
    """True when *fragment* is the next page of *table* rather than a new table."""
    if fragment.page not in (table.pages[-1], table.pages[-1] + 1):
        return False
    title = fragment.title.casefold()
    if title and "cont" not in title:
        return False
    if fragment.header is None:
        return fragment.width == table.width
    return table.raw_header is not None and [c.casefold() for c in fragment.header] == [
        c.casefold() for c in table.raw_header
    ]


def tables_from_openchemie(raw_tables: list[dict]) -> list[ExtractedTable]:
    """Clean and join OpenChemIE table results (with one-based ``page``) into tables."""
    building: list[_Building] = []
    for raw in sorted(
        (raw for raw in raw_tables or [] if isinstance(raw, dict)),
        key=lambda raw: raw.get("page") or 0,
    ):
        page = raw.get("page")
        if not isinstance(page, int):
            continue
        title = normalize_text(raw.get("title"))
        footnote = normalize_text(raw.get("footnote"))
        try:
            fragment = _fragment_from_openchemie(raw, page, title, footnote)
        except Exception:
            logger.warning("Skipping a table on page %s that could not be read", page, exc_info=True)
            continue
        if fragment is None:
            continue
        previous = building[-1] if building else None
        if previous is not None and _continues(previous, fragment):
            _, rows = _unstack(previous.raw_header, fragment.rows, fragment.width)
            previous.rows.extend(rows)
            if fragment.page not in previous.pages:
                previous.pages.append(fragment.page)
            if fragment.crop_png:
                previous.crops_png.append(fragment.crop_png)
            previous.footnote = previous.footnote or fragment.footnote
            continue
        columns, rows = _unstack(fragment.header, fragment.rows, fragment.width)
        building.append(
            _Building(
                title=title,
                pages=[fragment.page],
                raw_header=fragment.header,
                width=fragment.width,
                columns=columns,
                rows=rows,
                footnote=footnote,
                crops_png=[fragment.crop_png] if fragment.crop_png else [],
            )
        )
    return [
        ExtractedTable(
            id=f"T{index}",
            title=table.title,
            pages=table.pages,
            columns=table.columns,
            rows=table.rows,
            footnote=table.footnote,
            crops_png=table.crops_png,
        )
        for index, table in enumerate(building, start=1)
    ]


# --------------------------------------------------------------------------- linking


def _molecule_labels(molecules: list[ExtractedMolecule]) -> dict[str, list[ExtractedMolecule]]:
    """Map each normalized label or name to the molecules that carry it."""
    by_label: dict[str, list[ExtractedMolecule]] = {}
    for molecule in molecules:
        for part in (molecule.identifier or "").split(";"):
            for variant in _label_variants(part):
                if molecule not in by_label.setdefault(variant, []):
                    by_label[variant].append(molecule)
    return by_label


def detect_key_column(table: ExtractedTable, labels: set[str] | None = None) -> int | None:
    """Return the column holding compound labels or names, or None.

    A header such as "Ex No", "Compound", "Entry" or "Drug" decides first. Otherwise the column
    whose cells match the most known molecule labels wins, if at least two do. Failing that, a
    first column of compound-number-like values ("12", "12a") is taken.
    """
    for index, header in enumerate(table.columns):
        if header and _KEY_HEADER.match(header):
            return index
    labels = labels or set()
    best, best_hits = None, 1
    for index in range(len(table.columns)):
        hits = sum(bool(_label_variants(row[index]) & labels) for row in table.rows)
        if hits > best_hits:
            best, best_hits = index, hits
    if best is not None:
        return best
    if table.columns and _column_kind(table.rows, 0) == "id":
        return 0
    return None


def link_table_rows(
    tables: list[ExtractedTable], molecules: list[ExtractedMolecule]
) -> list[TableLink]:
    """Detect each table's key column (unless set) and suggest row-to-molecule links.

    Exact matches compare normalized labels; short labels with no exact match are then
    compared with OCR confusions folded ("Ia" matches "1a"). A blank key cell continues the
    row above (one compound listed with several indications). A row matching more than one
    molecule gets a link to each, all marked ambiguous.
    """
    index = _LabelIndex(molecules)
    links: list[TableLink] = []
    for table in tables:
        if table.key_column is None:
            table.key_column = detect_key_column(table, set(index.by_label))
        links.extend(index.suggest(table))
    return links


def suggest_links(
    table: ExtractedTable, molecules: list[ExtractedMolecule], rows: set[int] | None = None
) -> list[TableLink]:
    """Suggest links for the rows of one table (only *rows*, if given) by its key column."""
    return _LabelIndex(molecules).suggest(table, rows)


def row_keys(table: ExtractedTable) -> list[str]:
    """The key-column text each row is matched by, blank cells continuing the row above."""
    keys: list[str] = []
    current = ""
    for row in table.rows:
        cell = row[table.key_column] if table.key_column is not None else ""
        if cell:
            current = cell
        keys.append(current if (cell or any(row)) else "")
    return keys


class _LabelIndex:
    """Molecules by normalized label, and short labels with OCR confusions folded."""

    def __init__(self, molecules: list[ExtractedMolecule]) -> None:
        self.by_label = _molecule_labels(molecules)
        self.by_folded: dict[str, list[ExtractedMolecule]] = {}
        for label, matched in self.by_label.items():
            if len(label) <= _SHORT_LABEL:
                for molecule in matched:
                    group = self.by_folded.setdefault(label.translate(_OCR_FOLD), [])
                    if molecule not in group:
                        group.append(molecule)

    def suggest(self, table: ExtractedTable, rows: set[int] | None = None) -> list[TableLink]:
        if table.key_column is None:
            return []
        links: list[TableLink] = []
        for row_index, key in enumerate(row_keys(table)):
            if not key or (rows is not None and row_index not in rows):
                continue
            candidates, method = _candidates(key, self.by_label, self.by_folded)
            for molecule in candidates:
                links.append(
                    TableLink(
                        table_id=table.id,
                        row_index=row_index,
                        molecule_id=molecule.id,
                        label=key,
                        method=method,
                        ambiguous=len(candidates) > 1,
                    )
                )
        return links


def _candidates(
    key: str,
    by_label: dict[str, list[ExtractedMolecule]],
    by_folded: dict[str, list[ExtractedMolecule]],
) -> tuple[list[ExtractedMolecule], str]:
    """Molecules matching *key* exactly, else by OCR-folded short label; and the method used."""
    found: list[ExtractedMolecule] = []
    for variant in _label_variants(key):
        for molecule in by_label.get(variant, []):
            if molecule not in found:
                found.append(molecule)
    if found:
        return found, "exact"
    for variant in _label_variants(key):
        if len(variant) <= _SHORT_LABEL:
            for molecule in by_folded.get(variant.translate(_OCR_FOLD), []):
                if molecule not in found:
                    found.append(molecule)
    return found, "ocr"
