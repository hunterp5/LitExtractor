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

"""PDF text fallbacks: the pdftotext shim and a ChemRxnExtractor-free paragraph source."""

from __future__ import annotations

import logging
import sys
import types
from typing import Any

logger = logging.getLogger(__name__)


def preload_pdftotext() -> None:
    """
    Import ``pdftotext`` before OpenCV/layoutparser change the DLL search path.

    On Windows, importing OpenChemIE first then ``pdftotext`` often fails with
    ``DLL load failed ... cannot run %1``. Loading the extension first keeps it
    in ``sys.modules``. If the native module is missing, install a PyPDF2 shim.
    """
    if "pdftotext" in sys.modules:
        return
    try:
        import pdftotext  # noqa: F401
    except Exception as exc:
        logger.warning("Native pdftotext unavailable (%s); using a PyPDF2 shim.", exc)
        install_pdftotext_shim()


def install_pdftotext_shim() -> None:
    """Minimal ``pdftotext.PDF`` using PyPDF2 so ChemRxnExtractor can import."""
    from PyPDF2 import PdfReader

    class PDF(list):
        """Stand-in for ``pdftotext.PDF``: a list holding one text string per page."""

        def __init__(self, handle) -> None:
            """Read every page of the open binary PDF *handle* with PyPDF2 into this list."""
            reader = PdfReader(handle)
            self.extend((page.extract_text() or "") for page in reader.pages)

    shim_module = types.ModuleType("pdftotext")
    shim_module.PDF = PDF
    shim_module.Error = RuntimeError
    sys.modules["pdftotext"] = shim_module


def ensure_chemrxnextractor_importable() -> None:
    """
    ChemRxnExtractor's vendored package can fail to import (broken trainer.py).

    Stub the top-level ``chemrxnextractor`` name so OpenChemIE can load; text
    reaction extraction will error later if that path is used.
    """
    try:
        from chemrxnextractor import RxnExtractor  # noqa: F401

        return
    except Exception as exc:
        logger.warning(
            "chemrxnextractor is not importable (%s); text-reaction extraction disabled.",
            exc,
        )
        for name in list(sys.modules):
            if name == "chemrxnextractor" or name.startswith("chemrxnextractor."):
                del sys.modules[name]

    class RxnExtractor:
        """Placeholder ``RxnExtractor`` that fails loudly if text-reaction extraction is used."""

        def __init__(self, *args, **kwargs) -> None:
            """Always raise, explaining that chemrxnextractor could not be imported."""
            raise RuntimeError(
                "chemrxnextractor failed to import in this environment, so "
                "reactions-from-text is unavailable. Figure extraction still works."
            )

    stub = types.ModuleType("chemrxnextractor")
    stub.RxnExtractor = RxnExtractor
    sys.modules["chemrxnextractor"] = stub


def paragraphs_from_page_text(content: str) -> list[list[str]]:
    """Split a page of PDF text into sentence lists (OpenChemIE ChemRxnExtractor logic).

    Text is split into blocks on blank lines (blocks containing a form feed are dropped);
    each block becomes a list of sentences, each ending with a newline.
    """
    blocks: list[list[str]] = []
    for raw_block in content.split("\n\n"):
        paragraph: list[str] = []
        if "\x0c" in raw_block:
            continue
        text = raw_block.replace("\n", " ").replace("- ", "-")
        sentence_start = 0
        position = 0
        while position < len(text):
            if text[position] == ".":
                if (
                    position != 0
                    and not text[position - 1].isdigit()
                    or position != len(text) - 1
                    and (text[position + 1] == " " or text[position + 1] == "\n")
                ):
                    paragraph.append(text[sentence_start : position + 1] + "\n")
                    while position < len(text) and text[position] != " ":
                        position += 1
                    sentence_start = position + 1
            position += 1
        if sentence_start != position:
            if text[position - 1] == " ":
                if position != 1:
                    position -= 1
                else:
                    blocks.append(paragraph)
                    continue
            if text[position - 1] != ".":
                paragraph.append(text[sentence_start:position] + ".\n")
            else:
                paragraph.append(text[sentence_start:position] + "\n")
        blocks.append(paragraph)
    return blocks


class PdfParagraphSource:
    """
    Duck-type for OpenChemIE's ChemRxnExtractor paragraph API.

    OpenChemIE uses ChemRxnExtractor only to pull PDF text for ChemNER. The real
    package is broken in this environment, so we supply paragraphs ourselves.
    """

    def __init__(self) -> None:
        """Start with no PDF loaded and no page limit."""
        self.pdf_file = ""
        self.pages: int | None = None
        self.pdf_text: list[str] = []

    def set_pdf_file(self, pdf: str) -> None:
        """Load the per-page text of the PDF at path *pdf* via ``pdftotext``."""
        import pdftotext

        self.pdf_file = pdf
        with open(pdf, "rb") as handle:
            self.pdf_text = list(pdftotext.PDF(handle))

    def set_pages(self, pages: int | None) -> None:
        """Set how many pages to read; ``None`` means every loaded page."""
        self.pages = pages

    def get_paragraphs_from_pdf(self, pages: int | None = None) -> list[dict]:
        """Return ``{"paragraphs", "page"}`` dicts (1-based page) for the first *pages* pages."""
        if pages is None:
            pages = self.pages
        if pages is None:
            pages = len(self.pdf_text)
        result = []
        for page_index in range(int(pages)):
            content = self.pdf_text[page_index] if page_index < len(self.pdf_text) else ""
            result.append(
                {
                    "paragraphs": paragraphs_from_page_text(content),
                    "page": page_index + 1,
                }
            )
        return result

    def extract_reactions_from_text(self) -> list[dict]:
        """Return no text reactions when ChemRxnExtractor is unavailable."""
        return []


def configure_openchemie_client(client: Any) -> None:
    """Attach Windows-safe PDF text source so ChemNER does not load ChemRxnExtractor."""
    client._chemrxnextractor = PdfParagraphSource()
    client._litextractor_text_reactions_supported = False
