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

"""Scoped torch/Transformers checkpoint-loading compatibility for OpenChemIE models."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from .cancellation import raise_if_cancelled
logger = logging.getLogger(__name__)

_allow_legacy_checkpoint_loads: ContextVar[bool] = ContextVar(
    "litextractor_allow_legacy_checkpoint_loads",
    default=False,
)


@contextmanager
def openchemie_checkpoint_loads() -> Iterator[None]:
    """Allow legacy OpenChemIE checkpoints only during a scoped extraction call."""
    token = _allow_legacy_checkpoint_loads.set(True)
    try:
        yield
    finally:
        _allow_legacy_checkpoint_loads.reset(token)


def patch_transformers_torch_load_check() -> None:
    """
    Transformers 4.49+ refuses ``torch.load`` on PyTorch < 2.6 (CVE-2025-32434).

    OpenChemIE / ChemNER still load Hugging Face ``.bin`` checkpoints. The version
    gate is bypassed only inside :func:`openchemie_checkpoint_loads`; elsewhere the
    original Transformers check remains active.
    """
    try:
        import transformers.utils.import_utils as import_utils
    except ImportError:
        return
    original_check = getattr(import_utils, "check_torch_load_is_safe", None)
    if not callable(original_check):
        return
    if getattr(original_check, "_litextractor_patched", False):
        return

    def _check_torch_load_is_safe() -> None:
        """Skip the version gate inside OpenChemIE checkpoint loads; otherwise defer to it."""
        if _allow_legacy_checkpoint_loads.get():
            return None
        original_check()

    _check_torch_load_is_safe._litextractor_patched = True  # type: ignore[attr-defined]
    _check_torch_load_is_safe.__wrapped__ = original_check  # type: ignore[attr-defined]
    import_utils.check_torch_load_is_safe = _check_torch_load_is_safe
    try:
        import transformers.modeling_utils as modeling_utils

        if hasattr(modeling_utils, "check_torch_load_is_safe"):
            setattr(modeling_utils, "check_torch_load_is_safe", _check_torch_load_is_safe)
    except Exception:
        logger.debug("Could not patch transformers.modeling_utils check", exc_info=True)
    logger.info("Scoped Transformers torch.load compatibility to OpenChemIE model calls.")


def patch_torch_load_weights_only_default() -> None:
    """Keep OpenChemIE checkpoints loadable if the user later upgrades to torch 2.6+."""
    try:
        import torch
    except ImportError:
        return
    original_load = torch.load
    if getattr(original_load, "_litextractor_patched", False):
        return

    def _load(*args: Any, **kwargs: Any) -> Any:
        """Call ``torch.load`` after a cancel check, defaulting ``weights_only=False`` in scope."""
        raise_if_cancelled()
        if _allow_legacy_checkpoint_loads.get():
            kwargs.setdefault("weights_only", False)
        return original_load(*args, **kwargs)

    _load._litextractor_patched = True  # type: ignore[attr-defined]
    _load.__wrapped__ = original_load  # type: ignore[attr-defined]
    torch.load = _load
