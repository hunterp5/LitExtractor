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

from dataclasses import dataclass, field

from .crop_context import DEFAULT_MOLECULE_CROP_MARGIN


@dataclass
class ExtractOptions:
    figures: bool = True
    text: bool = True
    corefs: bool = False
    reactions: bool = False
    merge_by_inchi: bool = True
    first_page: int = 1
    num_pages: int | None = None
    max_molecules: int | None = None
    batch_size: int = 16
    device: str = "cpu"
    crop_margin: float = DEFAULT_MOLECULE_CROP_MARGIN


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

    def __post_init__(self) -> None:
        if not self.sources:
            self.sources = [self.source]


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
