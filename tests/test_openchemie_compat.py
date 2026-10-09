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

from __future__ import annotations

import sys

import pytest

from patentextractor.openchemie_compat import (
    dropbox_direct_url,
    install_pdftotext_shim,
    looks_like_html,
    paragraphs_from_page_text,
    preload_pdftotext,
    safe_http_cache_filename,
)


def test_pdftotext_shim_reads_pages(tmp_path):
    from PyPDF2 import PdfWriter

    pdf_path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with pdf_path.open("wb") as handle:
        writer.write(handle)

    sys.modules.pop("pdftotext", None)
    install_pdftotext_shim()
    import pdftotext

    with pdf_path.open("rb") as handle:
        pages = pdftotext.PDF(handle)
    assert len(pages) == 1


def test_preload_pdftotext_is_idempotent():
    preload_pdftotext()
    preload_pdftotext()
    assert "pdftotext" in sys.modules


def test_dropbox_cache_filename_strips_query():
    url = "https://www.dropbox.com/s/gxy11xkkiwnpgog/publaynet-tf_efficientdet_d1.pth.tar?dl=1"
    name = safe_http_cache_filename(url)
    assert name == "publaynet-tf_efficientdet_d1.pth.tar"
    assert "?" not in name


def test_huggingface_weight_url_for_publaynet():
    from patentextractor.openchemie_compat import huggingface_weight_url

    url = huggingface_weight_url("publaynet-tf_efficientdet_d1.pth.tar")
    assert url is not None
    assert "huggingface.co/layoutparser/efficientdet" in url


def test_dropbox_direct_url():
    url = "https://www.dropbox.com/s/gxy11xkkiwnpgog/publaynet-tf_efficientdet_d1.pth.tar?dl=1"
    assert dropbox_direct_url(url) == (
        "https://dl.dropboxusercontent.com/s/gxy11xkkiwnpgog/publaynet-tf_efficientdet_d1.pth.tar"
    )


def test_looks_like_html(tmp_path):
    html = tmp_path / "fake.pth.tar"
    html.write_text("<!DOCTYPE html>\n<html>", encoding="utf-8")
    bin_file = tmp_path / "real.bin"
    bin_file.write_bytes(b"PK\x03\x04")
    assert looks_like_html(str(html))
    assert not looks_like_html(str(bin_file))


def test_paragraphs_from_page_text_splits_sentences():
    blocks = paragraphs_from_page_text("Compound CCO was used. It is ethanol.")
    sentences = [s.strip() for block in blocks for s in block]
    assert any("CCO" in s for s in sentences)


def test_paragraph_source_disables_text_reactions_explicitly():
    from patentextractor.openchemie_compat import PdfParagraphSource

    assert PdfParagraphSource().extract_reactions_from_text() == []


def test_torch_load_compatibility_is_scoped_and_idempotent(monkeypatch):
    import torch

    from patentextractor.openchemie_compat import (
        openchemie_checkpoint_loads,
        patch_torch_load_weights_only_default,
    )

    calls = []

    def original_load(*args, **kwargs):
        calls.append(kwargs.copy())
        return kwargs

    monkeypatch.setattr(torch, "load", original_load)
    patch_torch_load_weights_only_default()
    patched_load = torch.load

    assert patched_load.__wrapped__ is original_load
    assert patched_load("checkpoint.pth") == {}
    with openchemie_checkpoint_loads():
        assert patched_load("checkpoint.pth") == {"weights_only": False}
        assert patched_load("checkpoint.pth", weights_only=True) == {"weights_only": True}

    patch_torch_load_weights_only_default()
    assert torch.load is patched_load
    assert calls == [{}, {"weights_only": False}, {"weights_only": True}]


def test_transformers_torch_load_gate_is_scoped(monkeypatch):
    import transformers.modeling_utils as modeling_utils
    import transformers.utils.import_utils as import_utils

    from patentextractor.openchemie_compat import (
        openchemie_checkpoint_loads,
        patch_transformers_torch_load_check,
    )

    calls = []

    def original_check():
        calls.append("checked")
        raise RuntimeError("unsafe torch version")

    monkeypatch.setattr(import_utils, "check_torch_load_is_safe", original_check)
    monkeypatch.setattr(modeling_utils, "check_torch_load_is_safe", original_check)
    patch_transformers_torch_load_check()
    patched_check = import_utils.check_torch_load_is_safe

    with pytest.raises(RuntimeError, match="unsafe torch version"):
        patched_check()
    with openchemie_checkpoint_loads():
        assert patched_check() is None
    assert modeling_utils.check_torch_load_is_safe is patched_check
    assert calls == ["checked"]


def test_moldetect_crop_expansion_uses_real_context_pixels():
    import numpy as np

    from patentextractor.openchemie_compat import _clean_bbox_output_with_context

    figure = np.zeros((100, 100, 3), dtype=np.uint8)
    figure[45:55, 82:86] = (255, 0, 0)  # edge atom outside the original x2=0.80 box
    detection = {"category": "[Mol]", "bbox": (0.2, 0.2, 0.8, 0.8), "score": 0.9}

    results, crops, references = _clean_bbox_output_with_context(
        [figure], [[detection]], margin_fraction=0.18
    )

    assert len(results) == len(crops) == len(references) == 1
    crop = crops[0]
    assert crop.shape == (82, 82, 3)
    assert np.any(np.all(crop == (255, 0, 0), axis=2))
    assert np.array_equal(crop[0, 0], figure[9, 9])
    assert references[0]["image"] is crop


def test_parent_figure_crop_expansion_uses_page_pixels_and_clips_at_page_edge():
    import layoutparser as lp
    import numpy as np

    from patentextractor.openchemie_compat import _layout_with_source_context

    page = np.zeros((100, 120, 3), dtype=np.uint8)
    page[45:55, 103:108] = (255, 0, 0)
    block = lp.TextBlock(
        lp.Rectangle(20, 20, 100, 80), text="structure figure", type="Figure", score=0.95
    )
    layout = lp.Layout([block])

    expanded = _layout_with_source_context(layout, page, margin_fraction=0.1)
    crop = expanded[0].crop_image(page)

    assert expanded[0].coordinates == (12, 14, 108, 86)
    assert expanded[0].type == "Figure"
    assert expanded[0].score == 0.95
    assert np.any(np.all(crop == (255, 0, 0), axis=2))
    assert block.coordinates == (20, 20, 100, 80)

    edge_block = lp.TextBlock(lp.Rectangle(110, 10, 119, 40), type="Figure")
    edge_layout = _layout_with_source_context(lp.Layout([edge_block]), page, margin_fraction=0.5)
    assert edge_layout[0].coordinates == (105, 0, 120, 55)
