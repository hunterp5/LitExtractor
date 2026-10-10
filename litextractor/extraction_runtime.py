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

"""OpenChemIE dependency checks, device selection, diagnostics, and client loading."""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any

from .extraction_errors import ExtractorUnavailableError
from .model_runtime import get_cached_openchemie_client

logger = logging.getLogger(__name__)

__all__ = [
    "build_openchemie_import_diagnostic",
    "cuda_available",
    "load_openchemie",
    "missing_openchemie_runtime_dependencies",
    "resolve_torch_device",
]


def cuda_available() -> bool:
    """Return True only when torch has a working CUDA runtime and at least one GPU."""
    try:
        import torch
    except Exception:
        return False

    cuda_mod = getattr(torch, "cuda", None)
    if cuda_mod is None:
        return False
    try:
        return bool(cuda_mod.is_available() and cuda_mod.device_count() > 0)
    except Exception:
        return False


def resolve_torch_device(device: str = "cpu") -> str:
    """Return the runtime device string, falling back to CPU when CUDA is unavailable."""
    requested = (device or "cpu").lower()
    if requested == "cuda" and cuda_available():
        return "cuda"
    return "cpu"


def missing_openchemie_runtime_dependencies() -> list[str]:
    """Return only genuine missing top-level modules for the OpenChemIE runtime stack."""
    required = [
        "torch",
        "layoutparser",
        "easyocr",
        "IPython",
        "openchemie",
        "matplotlib",
        "seqeval",
    ]
    missing: list[str] = []
    for module_name in required:
        try:
            module_spec = importlib.util.find_spec(module_name)
        except (ImportError, ValueError):
            # This is usually a dependency-version mismatch inside an installed package,
            # not a missing module. Those are diagnosed separately below.
            continue
        if module_spec is None:
            missing.append(module_name)
    return missing


def build_openchemie_import_diagnostic(exc: ImportError, *, pdf_path: str | None = None) -> str:
    """Turn an OpenChemIE import failure into a precise compatibility diagnosis."""
    text = str(exc)
    lower = text.lower()
    sample_name = "ddr2.pdf" if pdf_path is None else Path(pdf_path).name

    if "cannot import name" in lower or "albumentations" in lower or "safe_rotate_enlarged_img_size" in lower:
        mismatch_hint = (
            "This is not a missing-module error: OpenChemIE is installed, but a dependency "
            "in the runtime stack is incompatible with the installed version set."
        )
        install_hint = "python -m pip install --no-deps -r requirements.txt"
        lines = [
            f"OpenChemIE could not be imported while processing '{sample_name}'.",
            f"Original import error: {exc}",
            "",
            mismatch_hint,
            "",
            "The usual cause is an outdated or incompatible albumentations/transformers stack. "
            "This project expects the pinned runtime in requirements.txt.",
            "",
            "Suggested next steps:",
            "  1. Reinstall the project runtime from the repo requirements in the active venv.",
            f"  2. Run: {install_hint}",
            "  3. Ensure you are using the project venv, not a system or Miniconda Python.",
            "  4. If the issue persists, upgrade/downgrade the stack to the pinned versions in requirements.txt.",
        ]
        return "\n".join(lines)

    if "pdftotext" in lower:
        lines = [
            f"OpenChemIE could not be imported while processing '{sample_name}'.",
            f"Original import error: {exc}",
            "",
            "This project uses a Windows-safe fallback for pdftotext when the native module is not available. "
            "The app should install the PyPDF2 shim automatically before importing OpenChemIE.",
            "",
            "Suggested next steps:",
            "  1. Make sure the app is launched from the project venv, not a system Python.",
            "  2. Reinstall the project runtime from requirements.txt in that venv.",
            "  3. Confirm the runtime stack is not mixed with a separate Miniconda or global install.",
            "  4. If this still fails, reinstall the project venv and re-run the pinned dependency setup.",
        ]
        return "\n".join(lines)

    missing: list[str] = []
    if isinstance(exc, ModuleNotFoundError) and exc.name:
        missing.append(exc.name)

    for module_name in (
        "layoutparser",
        "torch",
        "openchemie",
        "pytorch",
        "pypdf2",
        "pdftotext",
        "matplotlib",
        "seqeval",
        "easyocr",
        "IPython",
    ):
        if module_name in lower and module_name not in missing:
            missing.append(module_name)

    if not missing:
        missing = missing_openchemie_runtime_dependencies() or [
            "layoutparser",
            "torch",
            "openchemie",
        ]

    install_hint = "python -m pip install " + " ".join(missing[:2])
    lines = [
        f"OpenChemIE could not be imported while processing '{sample_name}'.",
        f"Original import error: {exc}",
        "",
        "Likely missing dependency: " + ", ".join(missing),
        "",
        "This project requires a compatible OpenChemIE runtime, including layoutparser "
        "for the model stack and a Python-compatible torch build.",
        "",
        "Suggested next steps:",
        "  1. Ensure the app is using the project venv or a conda env with OpenChemIE installed.",
        f"  2. Install the missing dependency: {install_hint}",
        "  3. Confirm torch is compatible with your Python version, then install OpenChemIE with --no-deps.",
        "  4. Install Poppler for your OS if PDF rendering still fails.",
    ]
    return "\n".join(lines)


def load_openchemie(device: str = "cpu") -> Any:
    """Import and construct OpenChemIE, raising a clear error if it is missing."""
    selected_device = resolve_torch_device(device)
    if device == "cuda" and selected_device == "cpu":
        logger.warning(
            "CUDA was requested for OpenChemIE, but no compatible NVIDIA GPU was detected; "
            "falling back to CPU."
        )

    def create_client() -> Any:
        from .openchemie_compat import configure_openchemie_client, prepare_openchemie_imports

        missing = missing_openchemie_runtime_dependencies()
        if missing:
            detail = ModuleNotFoundError(f"No module named '{missing[0]}'")
            raise ExtractorUnavailableError(build_openchemie_import_diagnostic(detail)) from detail

        prepare_openchemie_imports()
        try:
            import torch
            from openchemie import OpenChemIE
        except ImportError as exc:
            raise ExtractorUnavailableError(build_openchemie_import_diagnostic(exc)) from exc

        torch_device = torch.device(selected_device)
        logger.info("Loading OpenChemIE on %s", torch_device)
        client = OpenChemIE(device=torch_device)
        configure_openchemie_client(client)
        return client

    return get_cached_openchemie_client(selected_device, create_client)