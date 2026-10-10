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

# Top-level modules the OpenChemIE runtime stack needs at import time.
REQUIRED_RUNTIME_MODULES = (
    "torch",
    "layoutparser",
    "easyocr",
    "IPython",
    "openchemie",
    "matplotlib",
    "seqeval",
)

# Module names that, when mentioned in an ImportError, identify the missing package.
DIAGNOSTIC_MODULE_NAMES = (
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
)


def cuda_available() -> bool:
    """Return True only when torch has a working CUDA runtime and at least one GPU."""
    try:
        import torch

        return bool(torch.cuda.is_available() and torch.cuda.device_count() > 0)
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
    missing: list[str] = []
    for module_name in REQUIRED_RUNTIME_MODULES:
        try:
            module_spec = importlib.util.find_spec(module_name)
        except (ImportError, ValueError):
            # This is usually a dependency-version mismatch inside an installed package,
            # not a missing module. Those are diagnosed separately.
            continue
        if module_spec is None:
            missing.append(module_name)
    return missing


def build_openchemie_import_diagnostic(exc: ImportError, *, pdf_path: str | None = None) -> str:
    """Turn an OpenChemIE import failure into a precise, actionable compatibility diagnosis."""
    lowered_error = str(exc).lower()
    document_name = "ddr2.pdf" if pdf_path is None else Path(pdf_path).name
    header = [
        f"OpenChemIE could not be imported while processing '{document_name}'.",
        f"Original import error: {exc}",
        "",
    ]

    if (
        "cannot import name" in lowered_error
        or "albumentations" in lowered_error
        or "safe_rotate_enlarged_img_size" in lowered_error
    ):
        return "\n".join(header + _incompatible_stack_advice())
    if "pdftotext" in lowered_error:
        return "\n".join(header + _pdftotext_advice())
    return "\n".join(header + _missing_dependency_advice(exc, lowered_error))


def _incompatible_stack_advice() -> list[str]:
    """Advice for an import error caused by mismatched versions in the installed stack."""
    return [
        "This is not a missing-module error: OpenChemIE is installed, but a dependency "
        "in the runtime stack is incompatible with the installed version set.",
        "",
        "The usual cause is an outdated or incompatible albumentations/transformers stack. "
        "This project expects the pinned runtime in requirements.txt.",
        "",
        "Suggested next steps:",
        "  1. Reinstall the project runtime from the repo requirements in the active venv.",
        "  2. Run: python -m pip install --no-deps -r requirements.txt",
        "  3. Ensure you are using the project venv, not a system or Miniconda Python.",
        "  4. If the issue persists, upgrade/downgrade the stack to the pinned versions in "
        "requirements.txt.",
    ]


def _pdftotext_advice() -> list[str]:
    """Advice for a pdftotext import error (the app normally installs a PyPDF2 shim)."""
    return [
        "This project uses a Windows-safe fallback for pdftotext when the native module is not "
        "available. The app should install the PyPDF2 shim automatically before importing "
        "OpenChemIE.",
        "",
        "Suggested next steps:",
        "  1. Make sure the app is launched from the project venv, not a system Python.",
        "  2. Reinstall the project runtime from requirements.txt in that venv.",
        "  3. Confirm the runtime stack is not mixed with a separate Miniconda or global install.",
        "  4. If this still fails, reinstall the project venv and re-run the pinned dependency "
        "setup.",
    ]


def _missing_dependency_advice(exc: ImportError, lowered_error: str) -> list[str]:
    """Advice naming the dependencies that are probably missing."""
    missing: list[str] = []
    if isinstance(exc, ModuleNotFoundError) and exc.name:
        missing.append(exc.name)
    for module_name in DIAGNOSTIC_MODULE_NAMES:
        if module_name in lowered_error and module_name not in missing:
            missing.append(module_name)
    if not missing:
        missing = missing_openchemie_runtime_dependencies() or [
            "layoutparser",
            "torch",
            "openchemie",
        ]

    return [
        "Likely missing dependency: " + ", ".join(missing),
        "",
        "This project requires a compatible OpenChemIE runtime, including layoutparser "
        "for the model stack and a Python-compatible torch build.",
        "",
        "Suggested next steps:",
        "  1. Ensure the app is using the project venv or a conda env with OpenChemIE installed.",
        "  2. Install the missing dependency: python -m pip install " + " ".join(missing[:2]),
        "  3. Confirm torch is compatible with your Python version, then install OpenChemIE "
        "with --no-deps.",
        "  4. Install Poppler for your OS if PDF rendering still fails.",
    ]


def load_openchemie(device: str = "cpu") -> Any:
    """Import and construct OpenChemIE, raising a clear error if it is missing."""
    selected_device = resolve_torch_device(device)
    if device == "cuda" and selected_device == "cpu":
        logger.warning(
            "CUDA was requested for OpenChemIE, but no compatible NVIDIA GPU was detected; "
            "falling back to CPU."
        )

    def create_client() -> Any:
        """Import OpenChemIE with the compatibility patches applied and build a client."""
        from .compat_pdf_text import configure_openchemie_client
        from .openchemie_compat import prepare_openchemie_imports

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
