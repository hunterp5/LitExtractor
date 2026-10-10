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

"""Prompt cancellation of long model calls (uses tiny torch modules, no model weights)."""

from __future__ import annotations

import sys
import threading

import pytest

from litextractor.cancellation import cancel_on_model_forward
from litextractor.extraction import extract_from_pdf
from litextractor.extraction_errors import ExtractionCancelled
from litextractor.models import ExtractOptions

torch = pytest.importorskip("torch")


def _layers(count: int = 50):
    return torch.nn.Sequential(*(torch.nn.Linear(4, 4) for _ in range(count)))


def test_cancellation_interrupts_inference_within_a_few_layers():
    seen_layers = 0
    cancelled = False

    class CountingLinear(torch.nn.Linear):
        def forward(self, value):
            nonlocal seen_layers, cancelled
            seen_layers += 1
            if seen_layers == 3:
                cancelled = True
            return super().forward(value)

    model = torch.nn.Sequential(*(CountingLinear(4, 4) for _ in range(50)))
    with cancel_on_model_forward(lambda: cancelled):
        with pytest.raises(ExtractionCancelled):
            model(torch.zeros(1, 4))

    assert seen_layers < 10


def test_cancellation_is_not_swallowed_by_generic_exception_handlers():
    assert not issubclass(ExtractionCancelled, Exception)

    def third_party_loader() -> str:
        try:
            raise ExtractionCancelled("Extraction cancelled.")
        except Exception:
            return "swallowed"

    with pytest.raises(ExtractionCancelled):
        third_party_loader()


def test_hook_is_removed_when_the_context_exits():
    model = _layers(3)
    with cancel_on_model_forward(lambda: True):
        pass

    assert model(torch.zeros(1, 4)).shape == (1, 4)


def test_hook_is_removed_after_cancellation():
    model = _layers(3)
    with pytest.raises(ExtractionCancelled):
        with cancel_on_model_forward(lambda: True):
            model(torch.zeros(1, 4))

    assert model(torch.zeros(1, 4)).shape == (1, 4)


def test_hook_ignores_other_threads():
    model = _layers(3)
    outcome: list[object] = []

    def run_inference() -> None:
        outcome.append(model(torch.zeros(1, 4)).shape)

    with cancel_on_model_forward(lambda: True):
        worker = threading.Thread(target=run_inference)
        worker.start()
        worker.join(5)

    assert outcome == [torch.Size([1, 4])]


def test_without_a_callback_or_torch_the_context_is_a_no_op(monkeypatch):
    model = _layers(3)
    with cancel_on_model_forward(None):
        assert model(torch.zeros(1, 4)).shape == (1, 4)

    monkeypatch.setitem(sys.modules, "torch", None)
    with cancel_on_model_forward(lambda: True):
        pass


def test_checkpoint_loads_stop_when_cancelled(monkeypatch):
    from litextractor.compat_checkpoint import patch_torch_load_weights_only_default

    monkeypatch.setattr(torch, "load", lambda *_args, **_kwargs: "loaded")
    patch_torch_load_weights_only_default()

    assert torch.load("checkpoint.pth") == "loaded"
    with cancel_on_model_forward(lambda: False):
        assert torch.load("checkpoint.pth") == "loaded"
    with cancel_on_model_forward(lambda: True):
        with pytest.raises(ExtractionCancelled):
            torch.load("checkpoint.pth")
    assert torch.load("checkpoint.pth") == "loaded"


def test_molscribe_conversion_runs_in_process_and_stops_between_molecules(monkeypatch):
    import multiprocessing

    chemistry = pytest.importorskip("molscribe.chemistry")
    from litextractor.compat_figures import patch_empty_molscribe_results

    converted: list[tuple] = []
    cancelled = False

    def fake_convert(coords, symbols, edges, image=None, debug=False):
        nonlocal cancelled
        converted.append((coords, symbols, edges, image))
        cancelled = len(converted) == 2
        return f"smiles-{coords}", f"molfile-{coords}", True

    def no_pool(*_args, **_kwargs):
        raise AssertionError("molecule conversion must not spawn a process pool")

    monkeypatch.setattr(chemistry, "_convert_graph_to_smiles", fake_convert)
    monkeypatch.setattr(multiprocessing, "Pool", no_pool)
    patch_empty_molscribe_results()

    smiles, molfiles, success = chemistry.convert_graph_to_smiles(
        [1, 2, 3], ["a", "b", "c"], ["x", "y", "z"], images=["i1", "i2", "i3"]
    )
    assert smiles == ("smiles-1", "smiles-2", "smiles-3")
    assert molfiles == ("molfile-1", "molfile-2", "molfile-3")
    assert success == 1.0
    assert converted[0] == (1, "a", "x", "i1")
    assert chemistry.convert_graph_to_smiles([], [], []) == ([], [], 0.0)

    converted.clear()
    with cancel_on_model_forward(lambda: cancelled):
        with pytest.raises(ExtractionCancelled):
            chemistry.convert_graph_to_smiles([1, 2, 3, 4], list("abcd"), list("wxyz"))
    assert len(converted) == 2


def test_pdfminer_page_parsing_checks_for_cancellation(monkeypatch):
    high_level = pytest.importorskip("pdfminer.high_level")
    from litextractor.compat_figures import patch_pdfminer_cancellation

    parsed: list[str] = []
    monkeypatch.setattr(high_level, "extract_pages", lambda pdf, **_kw: parsed.append(pdf) or [])
    patch_pdfminer_cancellation()
    patch_pdfminer_cancellation()
    assert high_level.extract_pages("a.pdf", page_numbers=[0]) == []

    with cancel_on_model_forward(lambda: True):
        with pytest.raises(ExtractionCancelled):
            high_level.extract_pages("b.pdf", page_numbers=[0])
    assert parsed == ["a.pdf"]


def test_extract_from_pdf_cancels_inside_a_long_model_call(tmp_path):
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    cancel_requested = threading.Event()
    layers_run = 0

    class CountingLinear(torch.nn.Linear):
        def forward(self, value):
            nonlocal layers_run
            layers_run += 1
            if layers_run == 5:
                cancel_requested.set()
            return super().forward(value)

    model = torch.nn.Sequential(*(CountingLinear(4, 4) for _ in range(1000)))

    class SlowClient:
        def extract_molecules_from_figures_in_pdf(self, _pdf, **_kwargs):
            model(torch.zeros(1, 4))
            return []

    with pytest.raises(ExtractionCancelled):
        extract_from_pdf(
            str(pdf),
            ExtractOptions(text=False, corefs=False),
            client=SlowClient(),
            should_cancel=cancel_requested.is_set,
        )

    assert layers_run < 20
    assert model(torch.zeros(1, 4)).shape == (1, 4)
