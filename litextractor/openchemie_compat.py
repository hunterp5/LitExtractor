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

"""Windows-friendly OpenChemIE import and runtime workarounds.

This module is the stable entry point. The individual workarounds live in focused modules:

- :mod:`.compat_checkpoint` — scoped ``torch.load`` / Transformers checkpoint gates
- :mod:`.compat_pdf_text` — ``pdftotext`` shim, ChemRxnExtractor stub, paragraph source
- :mod:`.compat_figures` — MolScribe, molecule-crop, layout-context, and page-fallback patches
- :mod:`.http_weights` — model-weight downloads and iopath cache naming
"""

from __future__ import annotations

import logging
import os

from .compat_checkpoint import (
    _allow_legacy_checkpoint_loads,
    openchemie_checkpoint_loads,
    patch_torch_load_weights_only_default,
    patch_transformers_torch_load_check,
)
from .compat_figures import (
    _clean_bbox_output_with_context,
    _layout_with_source_context,
    patch_empty_molscribe_results,
    patch_openchemie_figure_fallback,
    patch_openchemie_layout_crop_context,
    patch_openchemie_molecule_crops,
)
from .compat_pdf_text import (
    PdfParagraphSource,
    configure_openchemie_client,
    ensure_chemrxnextractor_importable,
    install_pdftotext_shim,
    paragraphs_from_page_text,
    preload_pdftotext,
)
from .http_weights import (
    LAYOUTPARSER_HF_WEIGHTS,
    download_url_to_file,
    dropbox_direct_url,
    huggingface_weight_url,
    looks_like_html,
    patch_iopath_http_cache_filenames,
    safe_http_cache_filename,
)

logger = logging.getLogger(__name__)

__all__ = [
    "LAYOUTPARSER_HF_WEIGHTS",
    "PdfParagraphSource",
    "_allow_legacy_checkpoint_loads",
    "_clean_bbox_output_with_context",
    "_layout_with_source_context",
    "configure_openchemie_client",
    "download_url_to_file",
    "dropbox_direct_url",
    "ensure_chemrxnextractor_importable",
    "huggingface_weight_url",
    "install_pdftotext_shim",
    "looks_like_html",
    "openchemie_checkpoint_loads",
    "paragraphs_from_page_text",
    "patch_empty_molscribe_results",
    "patch_iopath_http_cache_filenames",
    "patch_openchemie_figure_fallback",
    "patch_openchemie_layout_crop_context",
    "patch_openchemie_molecule_crops",
    "patch_torch_load_weights_only_default",
    "patch_transformers_torch_load_check",
    "prepare_openchemie_imports",
    "preload_pdftotext",
    "safe_http_cache_filename",
]


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
