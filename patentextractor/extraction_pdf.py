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

"""PDF page-window slicing and restoration of original page numbers."""

from __future__ import annotations

import tempfile
from numbers import Integral

from .extraction_errors import ExtractorUnavailableError
from .models import ExtractedMolecule, ExtractedReaction

def slice_pdf_pages(pdf_path: str, first_page: int, num_pages: int | None) -> tuple[str, int, bool]:
    """Restrict a PDF to a page window and return its path, offset, and temp-file flag.

    ``first_page`` is 1-based. A zero ``num_pages`` means process through the end.
    When the window starts at page 1, the original path is returned unchanged.
    """
    if isinstance(first_page, bool) or not isinstance(first_page, Integral):
        raise TypeError("first_page must be an integer")
    if first_page < 1:
        raise ValueError("first_page must be at least 1")
    if num_pages is not None:
        if isinstance(num_pages, bool) or not isinstance(num_pages, Integral):
            raise TypeError("num_pages must be a non-negative integer or None")
        if num_pages < 0:
            raise ValueError("num_pages must be non-negative; use 0 for unlimited")

    first_page = int(first_page)
    num_pages = None if num_pages is None else int(num_pages)
    if first_page == 1:
        return pdf_path, 0, False

    try:
        from PyPDF2 import PdfReader, PdfWriter
    except ImportError as exc:
        raise ExtractorUnavailableError(
            "PyPDF2 is required to start extraction after page 1."
        ) from exc
    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)
    start_index = min(first_page - 1, total_pages)
    end_index = (
        total_pages
        if not num_pages
        else min(total_pages, start_index + num_pages)
    )
    if start_index >= total_pages or start_index >= end_index:
        raise ValueError(f"Page range {first_page}… is outside this PDF ({total_pages} pages).")

    writer = PdfWriter()
    for page_index in range(start_index, end_index):
        writer.add_page(reader.pages[page_index])
    handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    try:
        writer.write(handle)
    finally:
        handle.close()
    return handle.name, start_index, True


def shift_result_pages(
    molecules: list[ExtractedMolecule],
    reactions: list[ExtractedReaction],
    offset: int,
) -> None:
    """Restore original 1-based page numbers after processing a sliced PDF."""
    if offset <= 0:
        return
    for molecule in molecules:
        shifted_pages = [page + offset for page in molecule.page_numbers]
        molecule.pages = shifted_pages
        molecule.page = shifted_pages[0] if shifted_pages else None
    for reaction in reactions:
        if reaction.page is not None:
            reaction.page += offset