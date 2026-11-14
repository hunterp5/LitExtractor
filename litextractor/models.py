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

"""Data contracts shared by extraction, UI, and export layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from numbers import Integral
from uuid import uuid4

#: MolScribe confidences below this are flagged. On sample papers, non-structures (protein
#: ribbons, numbered lists, reaction arrows) scored 0.0 to 0.5 and real structures mostly 0.8+.
LOW_CONFIDENCE_THRESHOLD = 0.5


@dataclass
class ExtractOptions:
    """User-selected settings controlling what is extracted from a PDF and how.

    Attributes:
        figures: Extract structures from figures.
        text: Extract structures named in running text.
        corefs: Resolve coreferences between figure structures and text mentions.
        reactions: Also extract reactions.
        tables: Keep the data tables found while detecting figures and link their rows to
            molecules by compound label or name.
        names_to_structures: Turn systematic names found in the text into structures with
            OPSIN (needs Java). Only used with ``text``.
        merge_by_inchi: Merge molecules that share an InChIKey into one record.
        first_page: 1-based first page to process.
        num_pages: Number of pages to process; ``None`` or ``0`` means all remaining pages.
        max_molecules: Cap on molecules kept; ``None`` or ``0`` means unlimited.
        batch_size: Batch size for model inference.
        device: Torch device name, e.g. ``"cpu"`` or ``"cuda"``; normalized to lowercase.
    """

    figures: bool = True
    text: bool = True
    corefs: bool = True
    reactions: bool = False
    tables: bool = True
    names_to_structures: bool = True
    merge_by_inchi: bool = True
    first_page: int = 1
    num_pages: int | None = None
    max_molecules: int | None = None
    batch_size: int = 16
    device: str = "cpu"

    def __post_init__(self) -> None:
        """Validate and normalize the options on construction."""
        self.validate()

    def validate(self) -> None:
        """Validate ranges and types before extraction starts."""
        if isinstance(self.first_page, bool) or not isinstance(self.first_page, Integral):
            raise TypeError("first_page must be an integer")
        self.first_page = int(self.first_page)
        if self.first_page < 1:
            raise ValueError("first_page must be at least 1")

        for name in ("num_pages", "max_molecules"):
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, Integral):
                raise TypeError(f"{name} must be a non-negative integer or None")
            value = int(value)
            if value < 0:
                raise ValueError(f"{name} must be non-negative; use 0 for unlimited")
            setattr(self, name, value)

        if isinstance(self.batch_size, bool) or not isinstance(self.batch_size, Integral):
            raise TypeError("batch_size must be an integer")
        self.batch_size = int(self.batch_size)
        if self.batch_size < 1:
            raise ValueError("batch_size must be at least 1")

        if not isinstance(self.device, str) or not self.device.strip():
            raise ValueError("device must be a non-empty string")
        self.device = self.device.strip().lower()


@dataclass
class ExtractedMolecule:
    """A single extracted chemical structure with its provenance and computed properties.

    Attributes:
        smiles: SMILES string for the structure.
        molfile: Optional MDL molfile block (may be filled in during enrichment).
        source: Origin of the first detection, e.g. ``"figure"`` or ``"text"``.
        page: Earliest known 1-based page number; kept in sync with ``pages``.
        score: Detector score for the structure's bounding box, if available.
        confidence: MolScribe's confidence (0 to 1) in the structure it read, if available.
            Below :data:`LOW_CONFIDENCE_THRESHOLD` the reading is flagged as low confidence.
        identifier: Label or name found near the structure (e.g. compound number).
        formula: Molecular formula computed by RDKit.
        molecular_weight: Molecular weight computed by RDKit.
        inchi_key: InChIKey computed by RDKit.
        crop_png: PNG bytes of the cropped region of the PDF page the structure came from.
        context: Surrounding text describing the structure.
        bbox: Detected bounding box, normalized to the figure image it was found in.
        figure_index: Position of that figure among the figures detected in this run, used to
            pair the structure with labels found in the same figure; ``None`` if not from one.
        sources: Every origin that detected this structure (all merged duplicates);
            ``source`` is the primary one.
        pages: Every page the structure appears on, ascending; ``page`` is the first.
        id: Stable identifier within a result, used by :class:`TableLink`. Not compared.
    """

    smiles: str
    molfile: str = ""
    source: str = "figure"
    page: int | None = None
    score: float | None = None
    confidence: float | None = None
    identifier: str = ""
    formula: str = ""
    molecular_weight: float | None = None
    inchi_key: str = ""
    crop_png: bytes | None = None
    context: str = ""
    bbox: tuple[float, ...] | None = None
    figure_index: int | None = None
    sources: list[str] = field(default_factory=list)
    pages: list[int] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid4().hex[:12], compare=False)

    def __post_init__(self) -> None:
        """Seed ``sources`` from ``source`` and reconcile ``page`` with ``pages``."""
        if not self.sources:
            self.sources = [self.source]
        self.pages = list(self.page_numbers)
        if self.pages:
            self.page = self.pages[0]

    @property
    def low_confidence(self) -> bool:
        """True when MolScribe reported a confidence below :data:`LOW_CONFIDENCE_THRESHOLD`."""
        return self.confidence is not None and self.confidence < LOW_CONFIDENCE_THRESHOLD

    @property
    def page_numbers(self) -> tuple[int, ...]:
        """All known pages in ascending order, including the legacy `page` value."""
        page_numbers = set(self.pages)
        if self.page is not None:
            page_numbers.add(self.page)
        return tuple(sorted(page_numbers))

    def add_page(self, page: int | None) -> None:
        """Add a page to the provenance while keeping `page` as the earliest page."""
        if page is None:
            return
        self.pages = sorted(set(self.page_numbers).union({page}))
        self.page = self.pages[0]


@dataclass
class ExtractedReaction:
    """A reaction extracted from a figure.

    Attributes:
        page: 1-based page the reaction was found on, if known.
        reactants: SMILES strings of the reactants.
        products: SMILES strings of the products.
        conditions: Free-text reaction conditions.
        source: Origin of the detection, e.g. ``"figure"``.
    """

    page: int | None
    reactants: list[str]
    products: list[str]
    conditions: str
    source: str = "figure"


@dataclass
class ExtractedTable:
    """A data table from the PDF, kept as the text it contains.

    Cells stay raw strings, so values such as ">10000", "<0.1" or "+++" survive unchanged.
    A table printed across several pages, or as side-by-side panels repeating the same columns,
    is joined into one table with one row per entry.

    Attributes:
        id: Short identifier within a result ("T1", "T2", ...).
        title: The caption, e.g. "Table 2. Inhibition of ...", or "" when none was found.
        pages: 1-based pages the table spans, ascending.
        columns: Column headers; "" where a header could not be read.
        rows: Cell text, one list per row, each as long as ``columns``.
        key_column: Index of the column holding compound labels or names, if one was found.
        footnote: Text printed under the table.
        crops_png: PNG images of the table as printed, one per page fragment.
    """

    id: str
    title: str
    pages: list[int]
    columns: list[str]
    rows: list[list[str]]
    key_column: int | None = None
    footnote: str = ""
    crops_png: list[bytes] = field(default_factory=list, repr=False)

    @property
    def name(self) -> str:
        """A short display name: "Table 2" from the caption, else "Table on p. N"."""
        import re

        match = re.match(r"\s*(table\s+[A-Za-z0-9]+)", self.title, re.IGNORECASE)
        if match:
            return " ".join(match.group(1).split()).rstrip(".")
        return f"Table on p. {self.pages[0]}" if self.pages else "Table"


@dataclass
class TableLink:
    """A suggested or confirmed pairing of one table row with one molecule.

    Attributes:
        table_id: The :attr:`ExtractedTable.id` of the table.
        row_index: Index of the row in :attr:`ExtractedTable.rows`.
        molecule_id: The :attr:`ExtractedMolecule.id` of the molecule.
        label: The key-column text that was matched.
        method: ``"exact"`` (labels equal once normalized), ``"ocr"`` (equal once common OCR
            confusions such as I/1 and O/0 are folded) or ``"manual"`` (set by the user).
        ambiguous: True when the row matched several molecules; none of them is chosen.
        confirmed: True once the user has accepted the link.
    """

    table_id: str
    row_index: int
    molecule_id: str
    label: str
    method: str = "exact"
    ambiguous: bool = False
    confirmed: bool = False


@dataclass
class ExtractionResult:
    """The complete output of one PDF extraction run.

    Attributes:
        pdf_path: Path of the processed PDF.
        molecules: Extracted molecules.
        reactions: Extracted reactions.
        warnings: Non-fatal problems encountered during extraction.
        tables: Data tables found in the PDF.
        table_links: Pairings of table rows with molecules.
        shown_table_columns: Table columns the user chose to show beside each molecule, as
            ``(table id, column index)`` pairs, in the order chosen.
        reactions_requested: True when the run was asked to extract reactions (so an empty
            reaction list means none were found, not that none were looked for).
    """

    pdf_path: str
    molecules: list[ExtractedMolecule]
    reactions: list[ExtractedReaction]
    warnings: list[str] = field(default_factory=list)
    tables: list[ExtractedTable] = field(default_factory=list)
    table_links: list[TableLink] = field(default_factory=list)
    shown_table_columns: list[tuple[str, int]] = field(default_factory=list)
    reactions_requested: bool = False
