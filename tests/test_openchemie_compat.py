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

from __future__ import annotations

import sys

import pytest

from litextractor.compat_pdf_text import (
    install_pdftotext_shim,
    paragraphs_from_page_text,
    preload_pdftotext,
)
from litextractor.http_weights import dropbox_direct_url, looks_like_html, safe_http_cache_filename


def test_pdftotext_shim_reads_pages(tmp_path):
    from PyPDF2 import PdfWriter

    pdf_path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with pdf_path.open("wb") as handle:
        writer.write(handle)

    missing = object()
    previous_module = sys.modules.get("pdftotext", missing)
    try:
        sys.modules.pop("pdftotext", None)
        install_pdftotext_shim()
        import pdftotext

        with pdf_path.open("rb") as handle:
            pages = pdftotext.PDF(handle)
        assert len(pages) == 1
    finally:
        if previous_module is missing:
            sys.modules.pop("pdftotext", None)
        else:
            sys.modules["pdftotext"] = previous_module


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
    from litextractor.http_weights import huggingface_weight_url

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


def test_torch_load_compatibility_is_scoped_and_idempotent(monkeypatch):
    import torch

    from litextractor.compat_checkpoint import (
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

    from litextractor.compat_checkpoint import (
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


def test_parent_figure_crop_expansion_uses_page_pixels_and_clips_at_page_edge():
    import layoutparser as lp
    import numpy as np

    from litextractor.compat_figures import _layout_with_source_context

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


def test_prepare_openchemie_imports_applies_patches_in_order(monkeypatch):
    from litextractor import openchemie_compat

    calls: list[str] = []
    ordered = (
        "preload_pdftotext",
        "ensure_chemrxnextractor_importable",
        "patch_torch_load_weights_only_default",
        "patch_transformers_torch_load_check",
        "patch_iopath_http_cache_filenames",
        "patch_empty_molscribe_results",
        "patch_pdfminer_cancellation",
        "patch_openchemie_layout_crop_context",
        "patch_openchemie_figure_fallback",
        "patch_openchemie_molecule_crops",
        "patch_openchemie_molecule_confidence",
    )
    for name in ordered:
        monkeypatch.setattr(openchemie_compat, name, lambda name=name: calls.append(name))

    openchemie_compat.prepare_openchemie_imports()

    assert calls == list(ordered)


def test_batched_rxnscribe_predictions_use_their_own_images(monkeypatch):
    import torch

    rxnscribe_interface = pytest.importorskip("rxnscribe.interface")
    from litextractor import compat_batching

    seen: list[tuple[str, object]] = []

    class Tokenizer:
        max_len = 4

        def sequence_to_data(self, seqs, scores, scale):
            del seqs, scores, scale
            return {"bboxes": [], "corefs": []}

    class FakeDetector:
        device = torch.device("cpu")
        tokenizer = {"bbox": Tokenizer(), "coref": Tokenizer(), "reaction": Tokenizer()}
        molscribe = None
        ocr_model = None

        def transform(self, image):
            del image
            return torch.zeros(1), {"scale": 1.0}

        def model(self, images, max_len):
            del max_len
            count = images.shape[0]
            return torch.zeros(count, 1), torch.zeros(count, 1)

    def record(kind):
        def _postprocess(raw, image=None, **kwargs):
            del kwargs
            seen.append((kind, image))
            return raw

        return _postprocess

    monkeypatch.setattr(rxnscribe_interface, "postprocess_coref_results", record("coref"))
    monkeypatch.setattr(rxnscribe_interface, "postprocess_bboxes", record("bbox"))
    monkeypatch.setattr(rxnscribe_interface, "postprocess_reactions", record("reaction"))
    for name in ("MolDetect", "RxnScribe"):
        cls = getattr(rxnscribe_interface, name)
        monkeypatch.setattr(cls, "predict_images", cls.predict_images)
    compat_batching.patch_rxnscribe_batch_images()

    images = [f"image-{index}" for index in range(5)]
    detector = FakeDetector()
    rxnscribe_interface.MolDetect.predict_images(detector, images, batch_size=2, coref=True)
    rxnscribe_interface.MolDetect.predict_images(detector, images, batch_size=2)
    rxnscribe_interface.RxnScribe.predict_images(detector, images, batch_size=2)

    for kind in ("coref", "bbox", "reaction"):
        assert [image for seen_kind, image in seen if seen_kind == kind] == images


def test_layout_context_widens_figure_blocks_but_not_table_blocks(monkeypatch):
    import sys
    import types

    import layoutparser as lp
    import numpy as np

    from litextractor import compat_figures

    seen: dict[str, object] = {}

    class FakeTableExtractor:
        def __init__(self):
            self.img = np.zeros((100, 100, 3), dtype=np.uint8)
            figure = lp.TextBlock(lp.Rectangle(20, 20, 70, 70), type="Figure")
            table = lp.TextBlock(lp.Rectangle(20, 20, 70, 70), type="Table")
            self.blocks = {"figure": lp.Layout([figure]), "table": lp.Layout([table])}

        def extract_figure_information(self):
            seen["figure"] = self.blocks["figure"][0].coordinates

        def extract_table_information(self):
            seen["table"] = self.blocks["table"][0].coordinates

    fake_module = types.ModuleType("openchemie.tableextractor")
    fake_module.TableExtractor = FakeTableExtractor
    monkeypatch.setitem(sys.modules, "openchemie", types.ModuleType("openchemie"))
    monkeypatch.setitem(sys.modules, "openchemie.tableextractor", fake_module)

    compat_figures.patch_openchemie_layout_crop_context()
    extractor = FakeTableExtractor()
    extractor.extract_figure_information()
    extractor.extract_table_information()

    assert seen["figure"] == (16, 16, 74, 74)
    assert seen["table"] == (20, 20, 70, 70)
    assert extractor.blocks["figure"][0].coordinates == (20, 20, 70, 70)


def test_pages_are_rendered_a_few_at_a_time(monkeypatch):
    import types

    from litextractor import compat_figures

    rendered = []

    def convert_from_path(pdf, first_page, last_page):
        rendered.append((first_page, last_page))
        return [f"page {number}" for number in range(first_page, last_page + 1)]

    fake = types.SimpleNamespace(
        pdfinfo_from_path=lambda pdf: {"Pages": 20}, convert_from_path=convert_from_path
    )
    monkeypatch.setitem(sys.modules, "pdf2image", fake)
    monkeypatch.setattr(compat_figures, "RENDER_BATCH_PAGES", 8)

    pages = compat_figures.rendered_pages("doc.pdf")
    first = next(pages)

    assert first == (0, "page 1") and rendered == [(1, 8)]  # nothing beyond the first batch
    assert [index for index, _page in pages] == list(range(1, 20))
    assert rendered == [(1, 8), (9, 16), (17, 20)]
    assert [i for i, _ in compat_figures.rendered_pages("doc.pdf", num_pages=10)] == list(range(10))
