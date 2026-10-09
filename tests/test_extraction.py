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

"""OpenChemIE result normalization and merge tests (no real models)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import patentextractor.extraction as extraction
from patentextractor.extraction import (
    ExtractOptions,
    ExtractedMolecule,
    ExtractionCancelled,
    _unpack_label,
    apply_speed_preset,
    cuda_available,
    enrich_molecule,
    extract_from_pdf,
    merge_molecules_by_inchi,
    molecules_from_figure_results,
    molecules_from_text_results,
    prioritize_molecules,
    reactions_from_pdf_results,
    resolve_torch_device,
    slice_pdf_pages,
)


class FakeClient:
    def extract_molecules_from_figures_in_pdf(self, pdf, **kwargs):
        del pdf, kwargs
        return [
            {
                "page": 0,
                "molecules": [
                    {
                        "smiles": "CCO",
                        "molfile": "",
                        "score": 0.91,
                        "bbox": (0.1, 0.1, 0.4, 0.4),
                        "image": None,
                    }
                ],
            }
        ]

    def extract_molecules_from_text_in_pdf(self, pdf, **kwargs):
        del pdf, kwargs
        text = "The compound CCO was used."
        start = text.index("CCO")
        return [
            {
                "page": 2,
                "molecules": [
                    {
                        "text": text,
                        "labels": [("MOL", start, start + 3)],
                    }
                ],
            }
        ]

    def extract_molecule_corefs_from_figures_in_pdf(self, pdf, **kwargs):
        del pdf, kwargs
        return []

    def extract_reactions_from_pdf(self, pdf, **kwargs):
        del pdf, kwargs
        return {
            "figures": [
                {
                    "page": 2,
                    "reactions": [
                        {
                            "reactants": [{"smiles": "CCO", "molfile": ""}],
                            "products": [{"smiles": "CC=O", "molfile": ""}],
                            "conditions": [{"text": ["rt, 1 h"]}],
                        }
                    ],
                }
            ],
            "text": [],
        }


def test_ddr2_sample_reports_missing_layoutparser_diagnostics():
    pdf_path = Path(__file__).resolve().parents[1] / "samples" / "ddr2.pdf"
    error = ModuleNotFoundError("No module named 'layoutparser'")
    message = (
        "OpenChemIE could not be imported while processing 'ddr2.pdf'.\n"
        "Original import error: No module named 'layoutparser'\n\n"
        "Likely missing dependency: layoutparser"
    )
    assert "ddr2.pdf" in message
    assert "layoutparser" in message.lower()
    assert pdf_path.exists()

    from patentextractor.extraction import build_openchemie_import_diagnostic

    diagnostic = build_openchemie_import_diagnostic(error, pdf_path=str(pdf_path))
    assert "ddr2.pdf" in diagnostic
    assert "layoutparser" in diagnostic.lower()
    assert "python -m pip install layoutparser" in diagnostic


def test_missing_openchemie_runtime_dependencies_detects_missing_modules(monkeypatch):
    import importlib

    def fake_import(name: str):
        if name in {"easyocr", "IPython"}:
            raise ModuleNotFoundError(f"No module named '{name}'")
        return object()

    monkeypatch.setattr(importlib, "import_module", fake_import)

    from patentextractor.extraction import missing_openchemie_runtime_dependencies

    missing = missing_openchemie_runtime_dependencies()
    assert "easyocr" in missing
    assert "IPython" in missing


def test_openchemie_import_error_is_not_reported_as_missing_dependency():
    from patentextractor.extraction import build_openchemie_import_diagnostic

    exc = ImportError(
        "cannot import name 'safe_rotate_enlarged_img_size' from "
        "'albumentations.augmentations.geometric.functional'"
    )
    message = build_openchemie_import_diagnostic(exc, pdf_path="ddr2.pdf")

    assert "missing dependency" not in message.lower()
    assert "albumentations" in message.lower()
    assert "incompatible" in message.lower()
    assert "ddr2.pdf" in message


def test_pdftotext_missing_uses_windows_shim_guidance():
    from patentextractor.extraction import (
        build_openchemie_import_diagnostic,
        missing_openchemie_runtime_dependencies,
    )

    missing = missing_openchemie_runtime_dependencies()
    assert "pdftotext" not in missing

    message = build_openchemie_import_diagnostic(
        ModuleNotFoundError("No module named 'pdftotext'"),
        pdf_path="ddr2.pdf",
    )
    assert "pdftotext" in message.lower()
    assert "pip install pdftotext" not in message.lower()
    assert "PyPDF2 shim" in message


def test_patch_empty_molscribe_results_updates_interface_alias():
    from patentextractor.openchemie_compat import patch_empty_molscribe_results

    import molscribe.chemistry as chemistry
    import molscribe.interface as interface_module

    patch_empty_molscribe_results()

    assert chemistry.convert_graph_to_smiles([], [], []) == ([], [], 0.0)
    assert interface_module.convert_graph_to_smiles([], [], []) == ([], [], 0.0)


def test_cuda_is_optional_and_falls_back_to_cpu(monkeypatch):
    monkeypatch.setattr(extraction, "cuda_available", lambda: False)
    assert extraction.cuda_available() is False
    assert resolve_torch_device("cuda") == "cpu"
    assert resolve_torch_device("cpu") == "cpu"


def test_figure_results_enrich_ethanol():
    recs = molecules_from_figure_results(
        [
            {
                "page": 4,
                "molecules": [{"smiles": "CCO", "molfile": "", "score": 0.5}],
            }
        ]
    )
    assert len(recs) == 1
    assert recs[0].formula == "C2H6O"
    assert recs[0].inchi_key
    assert recs[0].page == 4
    assert recs[0].molecular_weight is not None
    assert recs[0].molecular_weight == pytest.approx(46.069, abs=0.05)


def test_figure_results_expand_bbox_before_crop():
    import numpy as np

    full_image = np.zeros((100, 100, 3), dtype=np.uint8)
    full_image[25:75, 25:75] = 255

    recs = molecules_from_figure_results(
        [
            {
                "page": 4,
                "image": full_image,
                "molecules": [
                    {
                        "smiles": "CCO",
                        "molfile": "",
                        "score": 0.5,
                        "bbox": (0.25, 0.25, 0.75, 0.75),
                        "image": None,
                    }
                ],
            }
        ],
        crop_margin=0.18,
    )

    assert len(recs) == 1
    assert recs[0].bbox is not None
    assert recs[0].bbox[0] == pytest.approx(0.16)
    assert recs[0].bbox[1] == pytest.approx(0.16)
    assert recs[0].bbox[2] == pytest.approx(0.84)
    assert recs[0].bbox[3] == pytest.approx(0.84)
    assert recs[0].crop_png is not None


def test_figure_results_do_not_add_synthetic_border_to_existing_crop():
    import io

    import numpy as np
    from PIL import Image

    tight_crop = np.zeros((80, 80, 3), dtype=np.uint8)
    tight_crop[20:60, 20:60] = 255

    recs = molecules_from_figure_results(
        [
            {
                "page": 2,
                "image": None,
                "molecules": [
                    {
                        "smiles": "CCO",
                        "molfile": "",
                        "score": 0.5,
                        "bbox": (0.25, 0.25, 0.75, 0.75),
                        "image": tight_crop,
                    }
                ],
            }
        ],
        crop_margin=0.18,
    )

    assert len(recs) == 1
    assert recs[0].crop_png is not None
    with Image.open(io.BytesIO(recs[0].crop_png)) as img:
        assert img.size == (80, 80)
        assert np.array_equal(np.asarray(img), tight_crop)


def test_figure_results_prefer_existing_molecule_crop_over_tighter_figure_crop():
    import io

    import numpy as np
    from PIL import Image

    figure_image = np.zeros((120, 120, 3), dtype=np.uint8)
    figure_image[:, :] = 0
    figure_image[10:110, 10:110] = 255

    existing_crop = np.zeros((80, 80, 3), dtype=np.uint8)
    existing_crop[10:70, 10:70] = 255

    recs = molecules_from_figure_results(
        [
            {
                "page": 2,
                "image": figure_image,
                "molecules": [
                    {
                        "smiles": "CCO",
                        "molfile": "",
                        "score": 0.5,
                        "bbox": (0.2, 0.2, 0.8, 0.8),
                        "image": existing_crop,
                    }
                ],
            }
        ],
        crop_margin=0.18,
    )

    assert len(recs) == 1
    assert recs[0].crop_png is not None
    with Image.open(io.BytesIO(recs[0].crop_png)) as img:
        assert img.size == (80, 80)
        assert np.array_equal(np.asarray(img), existing_crop)


def test_figure_crop_uses_only_real_pixels_at_source_image_boundary():
    import io

    import numpy as np
    from PIL import Image

    full_image = np.zeros((120, 120, 3), dtype=np.uint8)
    full_image[10:110, 10:110] = 255

    recs = molecules_from_figure_results(
        [
            {
                "page": 1,
                "image": full_image,
                "molecules": [
                    {
                        "smiles": "CCO",
                        "molfile": "",
                        "score": 0.8,
                        "bbox": (0.04, 0.03, 0.30, 0.24),
                        "image": None,
                    }
                ],
            }
        ],
        crop_margin=0.28,
    )

    assert len(recs) == 1
    bbox = recs[0].bbox
    assert bbox is not None
    assert bbox[0] < 0.0
    assert bbox[1] < 0.0
    assert bbox[2] > 0.30
    assert bbox[3] > 0.24
    assert recs[0].crop_png is not None
    with Image.open(io.BytesIO(recs[0].crop_png)) as img:
        assert img.size == (45, 36)
        assert np.array_equal(np.asarray(img)[0, 0], full_image[0, 0])


def test_text_span_becomes_identifier_and_smiles():
    text = "The compound CCO was used."
    start = text.index("CCO")
    recs = molecules_from_text_results(
        [{"page": 1, "molecules": [{"text": text, "labels": [("MOL", start, start + 3)]}]}]
    )
    assert recs[0].identifier == "CCO"
    assert recs[0].smiles == "CCO"
    assert recs[0].source == "text"


@pytest.mark.integration
def test_ddr2_edge_structures_extract_end_to_end():
    configured_pdf = os.environ.get("PATENTEXTRACTOR_DDR2_SAMPLE")
    pdf_path = (
        Path(configured_pdf)
        if configured_pdf
        else Path(__file__).resolve().parents[1] / "samples" / "ddr2.pdf"
    )
    if not pdf_path.is_file():
        pytest.skip(
            "Set PATENTEXTRACTOR_DDR2_SAMPLE to a local DDR2 PDF to run this integration test."
        )
    result = extract_from_pdf(
        str(pdf_path),
        ExtractOptions(
            figures=True,
            text=False,
            corefs=False,
            reactions=False,
            merge_by_inchi=True,
            first_page=6,
            num_pages=1,
            max_molecules=50,
            batch_size=8,
        ),
    )
    assert len(result.molecules) > 0, result.warnings
    assert not any("Figure extraction failed" in item for item in result.warnings)
    smiles = [molecule.smiles for molecule in result.molecules]
    assert any("Cc1cn(-c2cc(" in value for value in smiles)
    assert any("CNC(=O)c1cc(Oc2ccc(NC(=O)" in value for value in smiles)
    assert {molecule.page for molecule in result.molecules} == {6}


def test_prioritize_molecules_ranks_valid_high_score_entries_first():
    ordered = prioritize_molecules(
        [
            ExtractedMolecule(smiles="not_a_real_molecule", score=0.1, source="figure", page=1),
            ExtractedMolecule(smiles="CCO", score=0.95, source="figure", page=1),
            ExtractedMolecule(smiles="C", score=0.05, source="text", page=2),
        ]
    )
    assert [m.smiles for m in ordered[:2]] == ["CCO", "C"]
    assert ordered[-1].smiles == "not_a_real_molecule"


def test_malformed_empty_label_tuples_are_ignored():
    assert _unpack_label(([], [], []), "The compound CCO was used.") == ("", 0, 0)
    assert _unpack_label([], "The compound CCO was used.") == ("", 0, 0)


def test_merge_by_inchi_combines_sources():
    a = enrich_molecule(ExtractedMolecule(smiles="CCO", source="figure", page=1))
    b = enrich_molecule(ExtractedMolecule(smiles="CCO", source="text", identifier="EtOH", page=2))
    merged = merge_molecules_by_inchi([a, b])
    assert len(merged) == 1
    assert merged[0].sources == ["figure", "text"]
    assert "EtOH" in merged[0].identifier


def test_extract_from_pdf_fake_client_merges_ethanol():
    result = extract_from_pdf(
        "dummy.pdf",
        ExtractOptions(figures=True, text=True, reactions=True, merge_by_inchi=True),
        client=FakeClient(),
    )
    ethanol = [m for m in result.molecules if m.inchi_key and m.formula == "C2H6O"]
    assert len(ethanol) == 1
    assert "figure" in ethanol[0].sources
    assert "text" in ethanol[0].sources
    assert ethanol[0].page == 1
    assert len(result.reactions) == 1
    assert result.reactions[0].products == ["CC=O"]
    assert result.reactions[0].page == 3


def test_extract_from_pdf_uses_selected_margin_for_openchemie_crop_and_resets_it():
    import io

    import numpy as np
    from PIL import Image

    from patentextractor.openchemie_compat import _clean_bbox_output_with_context

    class CropMarginClient(FakeClient):
        def extract_molecules_from_figures_in_pdf(self, pdf, **kwargs):
            del pdf, kwargs
            image = np.zeros((100, 100, 3), dtype=np.uint8)
            detections = [[{"category": "[Mol]", "bbox": (0.25, 0.25, 0.75, 0.75), "score": 0.9}]]
            figures, _, _ = _clean_bbox_output_with_context([image], detections)
            figures[0]["page"] = 0
            return figures

    result = extract_from_pdf(
        "dummy.pdf",
        ExtractOptions(
            figures=True,
            text=False,
            corefs=False,
            reactions=False,
            merge_by_inchi=False,
            crop_margin=0.20,
        ),
        client=CropMarginClient(),
    )

    assert len(result.molecules) == 1
    assert result.molecules[0].crop_png is not None
    with Image.open(io.BytesIO(result.molecules[0].crop_png)) as crop:
        assert crop.size == (70, 70)

    default_figure, default_crops, _ = _clean_bbox_output_with_context(
        [np.zeros((100, 100, 3), dtype=np.uint8)],
        [[{"category": "[Mol]", "bbox": (0.25, 0.25, 0.75, 0.75)}]],
    )
    assert default_figure
    assert default_crops[0].shape == (68, 68, 3)


def test_extract_from_pdf_reports_global_page_for_sliced_pdf(tmp_path):
    from PyPDF2 import PdfWriter

    pdf_path = tmp_path / "two-pages.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_blank_page(width=72, height=72)
    with pdf_path.open("wb") as handle:
        writer.write(handle)

    result = extract_from_pdf(
        str(pdf_path),
        ExtractOptions(
            figures=True,
            text=False,
            corefs=False,
            reactions=False,
            merge_by_inchi=False,
            first_page=2,
            num_pages=1,
        ),
        client=FakeClient(),
    )

    assert result.molecules
    assert {molecule.page for molecule in result.molecules} == {2}


def test_figure_reactions_survive_unavailable_text_reaction_backend():
    client = FakeClient()
    client._patentextractor_text_reactions_supported = False

    result = extract_from_pdf(
        "dummy.pdf",
        ExtractOptions(
            figures=False,
            text=False,
            corefs=False,
            reactions=True,
            merge_by_inchi=False,
        ),
        client=client,
    )

    assert len(result.reactions) == 1
    assert result.reactions[0].products == ["CC=O"]
    assert result.reactions[0].page == 3
    assert any("Text-based reaction extraction is unavailable" in item for item in result.warnings)


def test_cancel_between_steps():
    calls = {"n": 0}

    def should_cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 1

    with pytest.raises(ExtractionCancelled):
        extract_from_pdf(
            "dummy.pdf",
            ExtractOptions(figures=True, text=True, merge_by_inchi=False),
            client=FakeClient(),
            should_cancel=should_cancel,
        )


def test_reactions_from_pdf_results_conditions():
    rxns, mols = reactions_from_pdf_results(
        {
            "figures": [
                {
                    "page": 1,
                    "reactions": [
                        {
                            "reactants": [{"smiles": "C"}],
                            "products": [{"smiles": "CO"}],
                            "conditions": [{"text": ["heat"]}],
                        }
                    ],
                }
            ]
        }
    )
    assert rxns[0].conditions == "heat"
    assert {m.source for m in mols} == {"reaction_reactant", "reaction_product"}


def test_apply_speed_preset_quick_and_full():
    quick = apply_speed_preset("quick")
    assert quick.text is False
    assert quick.num_pages == 5
    assert quick.max_molecules == 50
    full = apply_speed_preset("full")
    assert full.text is True
    assert full.num_pages is None
    assert full.max_molecules is None


def test_max_molecules_trims_and_skips_text():
    class CappedClient(FakeClient):
        def __init__(self) -> None:
            self.text_called = False

        def extract_molecules_from_figures_in_pdf(self, pdf, **kwargs):
            del pdf, kwargs
            return [
                {
                    "page": 1,
                    "molecules": [
                        {"smiles": "C", "molfile": ""},
                        {"smiles": "CC", "molfile": ""},
                        {"smiles": "CCC", "molfile": ""},
                    ],
                }
            ]

        def extract_molecules_from_text_in_pdf(self, pdf, **kwargs):
            self.text_called = True
            return super().extract_molecules_from_text_in_pdf(pdf, **kwargs)

    client = CappedClient()
    result = extract_from_pdf(
        "dummy.pdf",
        ExtractOptions(
            figures=True,
            text=True,
            reactions=False,
            merge_by_inchi=False,
            max_molecules=2,
        ),
        client=client,
    )
    assert len(result.molecules) == 2
    assert client.text_called is False
    assert any("partial run" in item for item in result.warnings)


def test_slice_pdf_pages_identity_and_window(tmp_path):
    from PyPDF2 import PdfReader, PdfWriter

    pdf_path = tmp_path / "pages.pdf"
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=72, height=72)
    with pdf_path.open("wb") as handle:
        writer.write(handle)

    original, offset, is_temp = slice_pdf_pages(str(pdf_path), 1, 2)
    assert original == str(pdf_path)
    assert offset == 0
    assert is_temp is False

    sliced, offset, is_temp = slice_pdf_pages(str(pdf_path), 2, 1)
    try:
        assert is_temp is True
        assert offset == 1
        assert len(PdfReader(sliced).pages) == 1
    finally:
        if is_temp:
            Path(sliced).unlink(missing_ok=True)
