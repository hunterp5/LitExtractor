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

"""Figure-pipeline patches: layout context, molecule crops, page fallback, and MolScribe."""

from __future__ import annotations

import logging
from typing import Any

from .crop_context import (
    DEFAULT_LAYOUT_CONTEXT_MARGIN,
    current_molecule_crop_margin,
)

logger = logging.getLogger(__name__)


def patch_empty_molscribe_results() -> None:
    """Guard MolScribe against empty detection results from layoutparser or empty crops."""
    try:
        import molscribe.chemistry as chemistry
        import molscribe.interface as interface_module
    except Exception:
        return

    if getattr(chemistry.convert_graph_to_smiles, "_litextractor_patched", False) and getattr(
        interface_module.convert_graph_to_smiles, "_litextractor_patched", False
    ):
        return

    original = chemistry.convert_graph_to_smiles

    def _safe_convert_graph_to_smiles(coords, symbols, edges, images=None, num_workers=16):
        if not coords:
            return [], [], 0.0
        try:
            return original(coords, symbols, edges, images=images, num_workers=num_workers)
        except ValueError as exc:
            if "not enough values to unpack" in str(exc):
                return [], [], 0.0
            raise

    _safe_convert_graph_to_smiles._litextractor_patched = True  # type: ignore[attr-defined]
    chemistry.convert_graph_to_smiles = _safe_convert_graph_to_smiles
    interface_module.convert_graph_to_smiles = _safe_convert_graph_to_smiles


def _clean_bbox_output_with_context(
    figures: Any,
    bboxes: Any,
    margin_fraction: float | None = None,
) -> tuple[list[dict], list[Any], list[dict]]:
    """Crop molecule detections with real context pixels from the source figure.

    OpenChemIE's bundled implementation slices exactly at each MolDetect box, which
    can remove edge atoms before MolScribe sees the structure. Expand each normalized
    detector box first; clamp only to the source image's actual bounds and never
    synthesize border pixels. The active extraction option supplies the margin; direct
    calls without an explicit margin use the shared default.
    """
    import math

    import numpy as np

    results: list[dict] = []
    cropped: list[Any] = []
    references: list[dict] = []
    if margin_fraction is None:
        margin_fraction = current_molecule_crop_margin()
    margin_fraction = max(0.0, float(margin_fraction))
    for index, output in enumerate(bboxes):
        if index >= len(figures):
            break
        figure = np.asarray(figures[index])
        if figure.ndim < 2:
            results.append({"image": figures[index], "molecules": []})
            continue
        height, width = figure.shape[:2]
        data: dict[str, Any] = {"image": figures[index], "molecules": []}
        results.append(data)
        for detection in output:
            if detection.get("category") != "[Mol]":
                continue
            try:
                x0, y0, x1, y1 = (float(value) for value in detection["bbox"][:4])
            except (KeyError, TypeError, ValueError):
                continue
            if x1 <= x0 or y1 <= y0:
                continue
            pad_x = (x1 - x0) * max(0.0, float(margin_fraction))
            pad_y = (y1 - y0) * max(0.0, float(margin_fraction))
            left = max(0, min(width, math.floor((x0 - pad_x) * width)))
            top = max(0, min(height, math.floor((y0 - pad_y) * height)))
            right = max(0, min(width, math.ceil((x1 + pad_x) * width)))
            bottom = max(0, min(height, math.ceil((y1 + pad_y) * height)))
            crop = figure[top:bottom, left:right]
            if crop.size == 0:
                continue
            molecule: dict[str, Any] = {
                "bbox": detection["bbox"],
                "score": detection.get("score"),
                "image": crop,
            }
            cropped.append(crop)
            data["molecules"].append(molecule)
            references.append(molecule)
    return results, cropped, references


def patch_openchemie_molecule_crops() -> None:
    """Replace OpenChemIE's tight MolDetect slicing with context-preserving crops."""
    try:
        import openchemie.interface as interface_module
        import openchemie.utils as utils_module
    except Exception:
        return
    if getattr(_clean_bbox_output_with_context, "_litextractor_patched", False):
        return
    _clean_bbox_output_with_context._litextractor_patched = True  # type: ignore[attr-defined]
    utils_module.clean_bbox_output = _clean_bbox_output_with_context
    interface_module.clean_bbox_output = _clean_bbox_output_with_context


def _layout_with_source_context(
    blocks: Any,
    source_image: Any,
    margin_fraction: float = DEFAULT_LAYOUT_CONTEXT_MARGIN,
) -> Any:
    """Expand parent layout regions before figure/table crops are made.

    This fixed page-context margin is intentionally separate from the user-selected
    molecule margin, which is applied later inside each expanded figure crop.
    """
    import math

    import numpy as np

    if blocks is None or source_image is None:
        return blocks
    image = np.asarray(source_image)
    if image.ndim < 2:
        return blocks
    height, width = image.shape[:2]
    expanded_blocks = []
    for block in blocks:
        try:
            geometry = getattr(block, "block", block)
            x0, y0, x1, y1 = (float(value) for value in geometry.coordinates[:4])
            if x1 <= x0 or y1 <= y0:
                expanded_blocks.append(block)
                continue
            pad_x = (x1 - x0) * max(0.0, float(margin_fraction))
            pad_y = (y1 - y0) * max(0.0, float(margin_fraction))
            coords = (
                max(0, math.floor(x0 - pad_x)),
                max(0, math.floor(y0 - pad_y)),
                min(width, math.ceil(x1 + pad_x)),
                min(height, math.ceil(y1 + pad_y)),
            )
            expanded_geometry = type(geometry)(*coords)
            if geometry is block:
                expanded_blocks.append(expanded_geometry)
            else:
                expanded_blocks.append(block.set(block=expanded_geometry))
        except (AttributeError, TypeError, ValueError):
            expanded_blocks.append(block)
    try:
        return type(blocks)(expanded_blocks)
    except TypeError:
        return expanded_blocks


def patch_openchemie_layout_crop_context() -> None:
    """Keep page pixels around layout detections before creating figure/table crops."""
    try:
        from openchemie.tableextractor import TableExtractor
    except Exception:
        return
    if getattr(TableExtractor, "_litextractor_layout_context", False):
        return

    for key, method_name in (
        ("figure", "extract_figure_information"),
        ("table", "extract_table_information"),
    ):
        original = getattr(TableExtractor, method_name)

        def _extract_with_context(self, *args, _key=key, _original=original, **kwargs):
            original_blocks = self.blocks.get(_key)
            self.blocks[_key] = _layout_with_source_context(original_blocks, self.img)
            try:
                return _original(self, *args, **kwargs)
            finally:
                self.blocks[_key] = original_blocks

        _extract_with_context._litextractor_layout_context = True  # type: ignore[attr-defined]
        setattr(TableExtractor, method_name, _extract_with_context)
    TableExtractor._litextractor_layout_context = True


def patch_openchemie_figure_fallback() -> None:
    """If layoutparser finds no figure blocks, process the whole page as one figure."""
    try:
        from PIL import Image
        import numpy as np
        from openchemie.tableextractor import TableExtractor
    except Exception:
        return
    if getattr(TableExtractor, "_litextractor_page_fallback", False):
        return

    original = TableExtractor.extract_all_tables_and_figures

    def _fallback_extract_all_tables_and_figures(self, pages, pdfparser, content=None):
        ret = original(self, pages, pdfparser, content)
        if content == "figures" and not ret:
            for index, page in enumerate(pages):
                arr = np.asarray(page)
                ret.append(
                    {
                        "title": "",
                        "figure": {
                            "image": Image.fromarray(arr),
                            "bbox": [0.0, 0.0, 1.0, 1.0],
                        },
                        "table": {"bbox": [], "content": None},
                        "footnote": "",
                        "page": index,
                    }
                )
        return ret

    _fallback_extract_all_tables_and_figures._litextractor_page_fallback = True  # type: ignore[attr-defined]
    TableExtractor.extract_all_tables_and_figures = _fallback_extract_all_tables_and_figures
    TableExtractor._litextractor_page_fallback = True
