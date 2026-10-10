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

import math
from dataclasses import dataclass, field
from numbers import Integral, Real

from .crop_context import DEFAULT_MOLECULE_CROP_MARGIN


@dataclass
class ExtractOptions:
    """User-selected settings controlling what is extracted from a PDF and how.

    Attributes:
        figures: Extract structures from figures.
        text: Extract structures named in running text.
        corefs: Resolve coreferences between figure structures and text mentions.
        reactions: Also extract reactions.
        merge_by_inchi: Merge molecules that share an InChIKey into one record.
        first_page: 1-based first page to process.
        num_pages: Number of pages to process; ``None`` or ``0`` means all remaining pages.
        max_molecules: Cap on molecules kept; ``None`` or ``0`` means unlimited.
        batch_size: Batch size for model inference.
        device: Torch device name, e.g. ``"cpu"`` or ``"cuda"``; normalized to lowercase.
        crop_margin: Fractional margin (0 to 0.5) added around molecule crops.
    """

    figures: bool = True
    text: bool = True
    corefs: bool = True
    reactions: bool = False
    merge_by_inchi: bool = True
    first_page: int = 1
    num_pages: int | None = None
    max_molecules: int | None = None
    batch_size: int = 16
    device: str = "cpu"
    crop_margin: float = DEFAULT_MOLECULE_CROP_MARGIN

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

        if isinstance(self.crop_margin, bool) or not isinstance(self.crop_margin, Real):
            raise TypeError("crop_margin must be a number")
        self.crop_margin = float(self.crop_margin)
        if not math.isfinite(self.crop_margin) or not 0 <= self.crop_margin <= 0.5:
            raise ValueError("crop_margin must be finite and between 0 and 0.5")

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
        score: Confidence or quality score from extraction, if available.
        identifier: Label or name found near the structure (e.g. compound number).
        formula: Molecular formula computed by RDKit.
        molecular_weight: Molecular weight computed by RDKit.
        inchi_key: InChIKey computed by RDKit.
        crop_png: PNG bytes of the cropped region of the PDF page the structure came from.
        context: Surrounding text describing the structure.
        bbox: Bounding box of the structure on its page, if known.
        sources: Every origin that detected this structure (all merged duplicates);
            ``source`` is the primary one.
        pages: Every page the structure appears on, ascending; ``page`` is the first.
    """

    smiles: str
    molfile: str = ""
    source: str = "figure"
    page: int | None = None
    score: float | None = None
    identifier: str = ""
    formula: str = ""
    molecular_weight: float | None = None
    inchi_key: str = ""
    crop_png: bytes | None = None
    context: str = ""
    bbox: tuple[float, ...] | None = None
    sources: list[str] = field(default_factory=list)
    pages: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Seed ``sources`` from ``source`` and reconcile ``page`` with ``pages``."""
        if not self.sources:
            self.sources = [self.source]
        self.pages = list(self.page_numbers)
        if self.pages:
            self.page = self.pages[0]

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
class ExtractionResult:
    """The complete output of one PDF extraction run.

    Attributes:
        pdf_path: Path of the processed PDF.
        molecules: Extracted molecules.
        reactions: Extracted reactions.
        warnings: Non-fatal problems encountered during extraction.
    """

    pdf_path: str
    molecules: list[ExtractedMolecule]
    reactions: list[ExtractedReaction]
    warnings: list[str] = field(default_factory=list)
