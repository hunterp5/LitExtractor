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

"""Data contracts shared by extraction, UI, and export layers."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from numbers import Integral, Real

from .crop_context import DEFAULT_MOLECULE_CROP_MARGIN


@dataclass
class ExtractOptions:
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
    page: int | None
    reactants: list[str]
    products: list[str]
    conditions: str
    source: str = "figure"


@dataclass
class ExtractionResult:
    pdf_path: str
    molecules: list[ExtractedMolecule]
    reactions: list[ExtractedReaction]
    warnings: list[str] = field(default_factory=list)
