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


def patch_pdfminer_cancellation() -> None:
    """Check for cancellation before each pdfminer page parse.

    OpenChemIE parses one page per call, once per detected figure or table, in pure Python that
    no torch hook can interrupt. Checking before each call stops the chain at the next page.
    """
    try:
        import pdfminer.high_level as high_level
    except Exception:
        return
    original = high_level.extract_pages
    if getattr(original, "_litextractor_patched", False):
        return

    from .cancellation import raise_if_cancelled

    def _extract_pages(*args: Any, **kwargs: Any) -> Any:
        """Check for cancellation, then parse the page as pdfminer normally would."""
        raise_if_cancelled()
        return original(*args, **kwargs)

    _extract_pages._litextractor_patched = True  # type: ignore[attr-defined]
    _extract_pages.__wrapped__ = original  # type: ignore[attr-defined]
    high_level.extract_pages = _extract_pages


def patch_empty_molscribe_results() -> None:
    """Make MolScribe's graph-to-SMILES step empty-safe, pool-free, and cancellable.

    Upstream builds a fresh ``multiprocessing.Pool`` on every call. On Windows that spawns up
    to 16 processes that each re-import the scientific stack, and with its ``chunksize=128`` any
    call with at most 128 molecules is handled by one worker anyway. The per-molecule work is
    small, so converting in-process is faster and lets a cancel request stop between molecules.
    """
    try:
        import molscribe.chemistry as chemistry
        import molscribe.interface as interface_module
    except Exception:
        return

    if getattr(chemistry.convert_graph_to_smiles, "_litextractor_patched", False) and getattr(
        interface_module.convert_graph_to_smiles, "_litextractor_patched", False
    ):
        return

    def _convert_graph_to_smiles_in_process(
        coords, symbols, edges, images=None, num_workers=16  # noqa: ARG001
    ):
        """Convert predicted molecule graphs to SMILES one by one, stopping on cancellation.

        ``num_workers`` is accepted only for signature compatibility with upstream.
        """
        if not coords:
            return [], [], 0.0
        import numpy as np

        from .cancellation import raise_if_cancelled

        columns = (coords, symbols, edges) if images is None else (coords, symbols, edges, images)
        results = []
        for item in zip(*columns):
            raise_if_cancelled()
            results.append(chemistry._convert_graph_to_smiles(*item))
        smiles_list, molblock_list, success = zip(*results)
        return smiles_list, molblock_list, float(np.mean(success))

    _safe_convert_graph_to_smiles = _convert_graph_to_smiles_in_process
    _safe_convert_graph_to_smiles._litextractor_patched = True  # type: ignore[attr-defined]
    chemistry.convert_graph_to_smiles = _safe_convert_graph_to_smiles
    interface_module.convert_graph_to_smiles = _safe_convert_graph_to_smiles


def _padded_pixel_box(
    bbox: Any, margin_fraction: float, image_width: int, image_height: int
) -> tuple[int, int, int, int] | None:
    """Convert a normalized detector box to a padded ``(left, top, right, bottom)`` pixel box.

    The box is clamped to the image bounds. Returns None for malformed or empty boxes.
    """
    import math

    try:
        left, top, right, bottom = (float(value) for value in bbox[:4])
    except (KeyError, TypeError, ValueError):
        return None
    if right <= left or bottom <= top:
        return None
    horizontal_padding = (right - left) * margin_fraction
    vertical_padding = (bottom - top) * margin_fraction
    return (
        max(0, min(image_width, math.floor((left - horizontal_padding) * image_width))),
        max(0, min(image_height, math.floor((top - vertical_padding) * image_height))),
        max(0, min(image_width, math.ceil((right + horizontal_padding) * image_width))),
        max(0, min(image_height, math.ceil((bottom + vertical_padding) * image_height))),
    )


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
    import numpy as np

    results: list[dict] = []
    cropped_images: list[Any] = []
    molecule_references: list[dict] = []
    if margin_fraction is None:
        margin_fraction = current_molecule_crop_margin()
    margin_fraction = max(0.0, float(margin_fraction))
    for figure_index, detections in enumerate(bboxes):
        if figure_index >= len(figures):
            break
        figure_pixels = np.asarray(figures[figure_index])
        if figure_pixels.ndim < 2:
            results.append({"image": figures[figure_index], "molecules": []})
            continue
        figure_height, figure_width = figure_pixels.shape[:2]
        figure_result: dict[str, Any] = {"image": figures[figure_index], "molecules": []}
        results.append(figure_result)
        for detection in detections:
            if detection.get("category") != "[Mol]":
                continue
            pixel_box = _padded_pixel_box(
                detection.get("bbox", ()), margin_fraction, figure_width, figure_height
            )
            if pixel_box is None:
                continue
            left_pixel, top_pixel, right_pixel, bottom_pixel = pixel_box
            crop = figure_pixels[top_pixel:bottom_pixel, left_pixel:right_pixel]
            if crop.size == 0:
                continue
            molecule: dict[str, Any] = {
                "bbox": detection["bbox"],
                "score": detection.get("score"),
                "image": crop,
            }
            cropped_images.append(crop)
            figure_result["molecules"].append(molecule)
            molecule_references.append(molecule)
    return results, cropped_images, molecule_references


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
    image_pixels = np.asarray(source_image)
    if image_pixels.ndim < 2:
        return blocks
    image_height, image_width = image_pixels.shape[:2]
    expanded_blocks = []
    for block in blocks:
        try:
            geometry = getattr(block, "block", block)
            left, top, right, bottom = (float(value) for value in geometry.coordinates[:4])
            if right <= left or bottom <= top:
                expanded_blocks.append(block)
                continue
            horizontal_padding = (right - left) * max(0.0, float(margin_fraction))
            vertical_padding = (bottom - top) * max(0.0, float(margin_fraction))
            expanded_coordinates = (
                max(0, math.floor(left - horizontal_padding)),
                max(0, math.floor(top - vertical_padding)),
                min(image_width, math.ceil(right + horizontal_padding)),
                min(image_height, math.ceil(bottom + vertical_padding)),
            )
            expanded_geometry = type(geometry)(*expanded_coordinates)
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

    for block_key, method_name in (
        ("figure", "extract_figure_information"),
        ("table", "extract_table_information"),
    ):
        original = getattr(TableExtractor, method_name)

        def _extract_with_context(
            self, *args, _block_key=block_key, _original=original, **kwargs
        ):
            """Run the original extraction on layout blocks widened with page context."""
            original_blocks = self.blocks.get(_block_key)
            self.blocks[_block_key] = _layout_with_source_context(original_blocks, self.img)
            try:
                return _original(self, *args, **kwargs)
            finally:
                self.blocks[_block_key] = original_blocks

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

    def _extract_with_page_fallback(self, pages, pdfparser, content=None):
        """Run the original extraction; if no figures were found, treat each page as a figure."""
        results = original(self, pages, pdfparser, content)
        if content == "figures" and not results:
            for page_index, page_image in enumerate(pages):
                page_pixels = np.asarray(page_image)
                results.append(
                    {
                        "title": "",
                        "figure": {
                            "image": Image.fromarray(page_pixels),
                            "bbox": [0.0, 0.0, 1.0, 1.0],
                        },
                        "table": {"bbox": [], "content": None},
                        "footnote": "",
                        "page": page_index,
                    }
                )
        return results

    _extract_with_page_fallback._litextractor_page_fallback = True  # type: ignore[attr-defined]
    TableExtractor.extract_all_tables_and_figures = _extract_with_page_fallback
    TableExtractor._litextractor_page_fallback = True
