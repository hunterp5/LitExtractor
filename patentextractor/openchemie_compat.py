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

"""Windows-friendly OpenChemIE import and runtime workarounds."""

from __future__ import annotations

import logging
import os
import sys
import types
import uuid
from typing import Any
from urllib.parse import urlparse

from .crop_context import (
    DEFAULT_LAYOUT_CONTEXT_MARGIN,
    current_molecule_crop_margin,
)

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
        def __init__(self, handle) -> None:
            reader = PdfReader(handle)
            self.extend((page.extract_text() or "") for page in reader.pages)

    mod = types.ModuleType("pdftotext")
    mod.PDF = PDF
    mod.Error = RuntimeError
    sys.modules["pdftotext"] = mod


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
        def __init__(self, *args, **kwargs) -> None:
            raise RuntimeError(
                "chemrxnextractor failed to import in this environment, so "
                "reactions-from-text is unavailable. Figure extraction still works."
            )

    stub = types.ModuleType("chemrxnextractor")
    stub.RxnExtractor = RxnExtractor
    sys.modules["chemrxnextractor"] = stub


def safe_http_cache_filename(url: str) -> str:
    """Basename for an HTTP cache file, without query strings (illegal on Windows)."""
    path = urlparse(url).path.rstrip("/")
    name = path.split("/")[-1] if path else ""
    return name or "download.bin"


LAYOUTPARSER_HF_WEIGHTS: dict[str, tuple[str, str]] = {
    "publaynet-tf_efficientdet_d0.pth.tar": (
        "layoutparser/efficientdet",
        "PubLayNet/tf_efficientdet_d0/publaynet-tf_efficientdet_d0.pth.tar",
    ),
    "publaynet-tf_efficientdet_d1.pth.tar": (
        "layoutparser/efficientdet",
        "PubLayNet/tf_efficientdet_d1/publaynet-tf_efficientdet_d1.pth.tar",
    ),
    "mfd-tf_efficientdet_d0.pth.tar": (
        "layoutparser/efficientdet",
        "MFD/tf_efficientdet_d0/mfd-tf_efficientdet_d0.pth.tar",
    ),
    "mfd-tf_efficientdet_d1.pth.tar": (
        "layoutparser/efficientdet",
        "MFD/tf_efficientdet_d1/mfd-tf_efficientdet_d1.pth.tar",
    ),
}


def huggingface_weight_url(filename: str) -> str | None:
    """HTTP URL for a LayoutParser weight hosted on Hugging Face, if known."""
    spec = LAYOUTPARSER_HF_WEIGHTS.get(filename)
    if spec is None:
        return None
    repo, path = spec
    return f"https://huggingface.co/{repo}/resolve/main/{path}"


def dropbox_direct_url(url: str) -> str:
    """Convert a Dropbox share link to a direct file URL (avoids HTML landing pages)."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host in ("www.dropbox.com", "dropbox.com") and parsed.path.startswith("/s/"):
        return f"https://dl.dropboxusercontent.com{parsed.path}"
    return url


def looks_like_html(path: str) -> bool:
    """True if *path* starts with an HTML doctype (failed Dropbox download)."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(32).lstrip().lower()
    except OSError:
        return False
    return head.startswith(b"<!doctype") or head.startswith(b"<html")


def download_url_to_file(url: str, dest: str) -> None:
    """Download *url* to *dest*, trying Hugging Face then Dropbox, rejecting HTML."""
    import shutil
    from urllib.request import Request, urlopen

    filename = safe_http_cache_filename(url)
    spec = LAYOUTPARSER_HF_WEIGHTS.get(filename)
    if spec is not None:
        try:
            from huggingface_hub import hf_hub_download

            cached = hf_hub_download(repo_id=spec[0], filename=spec[1])
            if cached and os.path.isfile(cached) and not looks_like_html(cached):
                os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
                if os.path.abspath(cached) != os.path.abspath(dest):
                    shutil.copyfile(cached, dest)
                return
        except Exception as exc:
            logger.warning("Hugging Face hub download failed for %s: %s", filename, exc)

    candidates: list[str] = []
    hf_url = huggingface_weight_url(filename)
    if hf_url:
        candidates.append(hf_url)
    direct = dropbox_direct_url(url)
    if direct != url:
        candidates.append(direct)
    candidates.append(url)
    last_error: Exception | None = None
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    for candidate in candidates:
        tmp_path = dest + ".tmp"
        try:
            request = Request(
                candidate,
                headers={"User-Agent": "PatentExtractor/0.1 (layoutparser-weights)"},
            )
            with urlopen(request, timeout=120) as response, open(tmp_path, "wb") as handle:
                shutil.copyfileobj(response, handle)
            if looks_like_html(tmp_path):
                os.remove(tmp_path)
                last_error = RuntimeError(
                    f"Download from {candidate} returned HTML, not a model file."
                )
                continue
            os.replace(tmp_path, dest)
            return
        except Exception as exc:
            last_error = exc
            if os.path.isfile(tmp_path):
                os.remove(tmp_path)
    raise RuntimeError(f"Could not download a valid model file from {url}") from last_error


def patch_transformers_torch_load_check() -> None:
    """
    Transformers 4.49+ refuses ``torch.load`` on PyTorch < 2.6 (CVE-2025-32434).

    OpenChemIE / ChemNER still load Hugging Face ``.bin`` checkpoints. Torch 2.6
    would also break MolScribe (default ``weights_only=True``), so we keep 2.5
    and skip the transformers version gate for this trusted local use.
    """
    try:
        import transformers.utils.import_utils as import_utils
    except ImportError:
        return
    if getattr(import_utils.check_torch_load_is_safe, "_patentextractor_patched", False):
        return

    def _check_torch_load_is_safe() -> None:
        return None

    _check_torch_load_is_safe._patentextractor_patched = True  # type: ignore[attr-defined]
    import_utils.check_torch_load_is_safe = _check_torch_load_is_safe
    try:
        import transformers.modeling_utils as modeling_utils

        modeling_utils.check_torch_load_is_safe = _check_torch_load_is_safe
    except Exception:
        logger.debug("Could not patch transformers.modeling_utils check", exc_info=True)
    logger.info("Relaxed transformers torch.load version gate (PyTorch < 2.6).")


def patch_torch_load_weights_only_default() -> None:
    """Keep OpenChemIE checkpoints loadable if the user later upgrades to torch 2.6+."""
    try:
        import torch
    except ImportError:
        return
    load = torch.load
    if getattr(load, "_patentextractor_patched", False):
        return

    def _load(*args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("weights_only", False)
        return load(*args, **kwargs)

    _load._patentextractor_patched = True  # type: ignore[attr-defined]
    torch.load = _load


def patch_iopath_http_cache_filenames() -> None:
    """
    LayoutParser caches Dropbox URLs like ``file.pth.tar?dl=1``.

    The ``?`` is not a valid Windows filename, so portalocker raises EINVAL.
    urllib without a browser User-Agent also saves the HTML landing page, which
    then fails as ``invalid load key, '<'``.
    """
    try:
        from iopath.common.file_io import HTTPURLHandler, file_lock, get_cache_dir
    except ImportError:
        return
    if getattr(HTTPURLHandler, "_patentextractor_patched", False):
        return

    def _get_local_path(
        self, path: str, force: bool = False, cache_dir: str | None = None, **kwargs: Any
    ) -> str:
        self._check_kwargs(kwargs)
        parsed_url = urlparse(path)
        dirname = os.path.join(
            get_cache_dir(cache_dir), os.path.dirname(parsed_url.path.lstrip("/"))
        )
        filename = safe_http_cache_filename(path)
        if len(filename) > HTTPURLHandler.MAX_FILENAME_LEN:
            filename = filename[:100] + "_" + uuid.uuid4().hex
        cached = os.path.join(dirname, filename)
        need_download = (
            force
            or path not in self.cache_map
            or not os.path.isfile(cached)
            or looks_like_html(cached)
        )
        if need_download:
            with file_lock(cached):
                if force or not os.path.isfile(cached) or looks_like_html(cached):
                    logger.info("Downloading %s ...", path)
                    download_url_to_file(path, cached)
            logger.info("URL %s cached in %s", path, cached)
        self.cache_map[path] = cached
        return cached

    HTTPURLHandler._get_local_path = _get_local_path  # type: ignore[method-assign]
    HTTPURLHandler._patentextractor_patched = True
    logger.info("Patched iopath HTTP cache to strip query strings from filenames.")


def paragraphs_from_page_text(content: str) -> list[list[str]]:
    """Split a page of PDF text into sentence lists (OpenChemIE ChemRxnExtractor logic)."""
    blocks: list[list[str]] = []
    for line in content.split("\n\n"):
        paragraph: list[str] = []
        if "\x0c" in line:
            continue
        text = line.replace("\n", " ").replace("- ", "-")
        curind = 0
        i = 0
        while i < len(text):
            if text[i] == ".":
                if (
                    i != 0
                    and not text[i - 1].isdigit()
                    or i != len(text) - 1
                    and (text[i + 1] == " " or text[i + 1] == "\n")
                ):
                    paragraph.append(text[curind : i + 1] + "\n")
                    while i < len(text) and text[i] != " ":
                        i += 1
                    curind = i + 1
            i += 1
        if curind != i:
            if text[i - 1] == " ":
                if i != 1:
                    i -= 1
                else:
                    blocks.append(paragraph)
                    continue
            if text[i - 1] != ".":
                paragraph.append(text[curind:i] + ".\n")
            else:
                paragraph.append(text[curind:i] + "\n")
        blocks.append(paragraph)
    return blocks


class PdfParagraphSource:
    """
    Duck-type for OpenChemIE's ChemRxnExtractor paragraph API.

    OpenChemIE uses ChemRxnExtractor only to pull PDF text for ChemNER. The real
    package is broken in this environment, so we supply paragraphs ourselves.
    """

    def __init__(self) -> None:
        self.pdf_file = ""
        self.pages: int | None = None
        self.pdf_text: list[str] = []

    def set_pdf_file(self, pdf: str) -> None:
        import pdftotext

        self.pdf_file = pdf
        with open(pdf, "rb") as handle:
            self.pdf_text = list(pdftotext.PDF(handle))

    def set_pages(self, pages: int | None) -> None:
        self.pages = pages

    def get_paragraphs_from_pdf(self, pages: int | None = None) -> list[dict]:
        if pages is None:
            pages = self.pages
        if pages is None:
            pages = len(self.pdf_text)
        result = []
        for index in range(int(pages)):
            content = self.pdf_text[index] if index < len(self.pdf_text) else ""
            result.append(
                {
                    "paragraphs": paragraphs_from_page_text(content),
                    "page": index + 1,
                }
            )
        return result

    def extract_reactions_from_text(self) -> list[dict]:
        """Return no text reactions when ChemRxnExtractor is unavailable."""
        return []


def configure_openchemie_client(client: Any) -> None:
    """Attach Windows-safe PDF text source so ChemNER does not load ChemRxnExtractor."""
    client._chemrxnextractor = PdfParagraphSource()
    client._patentextractor_text_reactions_supported = False


def patch_empty_molscribe_results() -> None:
    """Guard MolScribe against empty detection results from layoutparser or empty crops."""
    try:
        import molscribe.chemistry as chemistry
        import molscribe.interface as interface_module
    except Exception:
        return

    if getattr(chemistry.convert_graph_to_smiles, "_patentextractor_patched", False) and getattr(
        interface_module.convert_graph_to_smiles, "_patentextractor_patched", False
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

    _safe_convert_graph_to_smiles._patentextractor_patched = True  # type: ignore[attr-defined]
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
    if getattr(_clean_bbox_output_with_context, "_patentextractor_patched", False):
        return
    _clean_bbox_output_with_context._patentextractor_patched = True  # type: ignore[attr-defined]
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
    if getattr(TableExtractor, "_patentextractor_layout_context", False):
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

        _extract_with_context._patentextractor_layout_context = True  # type: ignore[attr-defined]
        setattr(TableExtractor, method_name, _extract_with_context)
    TableExtractor._patentextractor_layout_context = True


def patch_openchemie_figure_fallback() -> None:
    """If layoutparser finds no figure blocks, process the whole page as one figure."""
    try:
        from PIL import Image
        import numpy as np
        from openchemie.tableextractor import TableExtractor
    except Exception:
        return
    if getattr(TableExtractor, "_patentextractor_page_fallback", False):
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

    _fallback_extract_all_tables_and_figures._patentextractor_page_fallback = True  # type: ignore[attr-defined]
    TableExtractor.extract_all_tables_and_figures = _fallback_extract_all_tables_and_figures
    TableExtractor._patentextractor_page_fallback = True


def prepare_openchemie_imports() -> None:
    """Call before ``from openchemie import OpenChemIE``."""
    import warnings

    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")

    logging.getLogger("transformers").setLevel(logging.ERROR)
    logging.getLogger("transformers.utils.hub").setLevel(logging.ERROR)
    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

    warnings.filterwarnings("ignore", category=FutureWarning, module=r"onmt\..*")
    warnings.filterwarnings("ignore", message=r".*torch\.cuda\.amp\.custom_fwd.*")
    warnings.filterwarnings("ignore", message=r".*torch\.cuda\.amp\.custom_bwd.*")
    warnings.filterwarnings("ignore", message=r"Some weights of BertForTokenClassification")
    warnings.filterwarnings(
        "ignore", message=r"You are using `torch.load` with `weights_only=False`"
    )
    warnings.filterwarnings("ignore", message=r"torch.meshgrid")
    warnings.filterwarnings(
        "ignore",
        message=r".*The following generation flags are not valid.*",
        category=UserWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message=r".*output_hidden_states.*",
        category=UserWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message=r".*We strongly recommend passing in an `attention_mask`.*",
        category=UserWarning,
    )
    preload_pdftotext()
    ensure_chemrxnextractor_importable()
    patch_torch_load_weights_only_default()
    patch_transformers_torch_load_check()
    patch_iopath_http_cache_filenames()
    patch_empty_molscribe_results()
    patch_openchemie_layout_crop_context()
    patch_openchemie_figure_fallback()
    patch_openchemie_molecule_crops()
