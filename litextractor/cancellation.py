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

"""Fine-grained cancellation for long, blocking OpenChemIE model calls."""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from .extraction_errors import ExtractionCancelled

_cancel_check: ContextVar[Callable[[], bool] | None] = ContextVar(
    "litextractor_cancel_check", default=None
)


def raise_if_cancelled() -> None:
    """Raise ``ExtractionCancelled`` if the active model-call scope has been cancelled.

    A no-op outside :func:`cancel_on_model_forward`, so it is safe to call from shared helpers.
    """
    check = _cancel_check.get()
    if check is not None and check():
        raise ExtractionCancelled("Extraction cancelled.")


@contextmanager
def cancel_on_model_forward(should_cancel: Callable[[], bool] | None) -> Iterator[None]:
    """Abort the current thread's model work soon after cancellation is requested.

    OpenChemIE runs each stage as one blocking call over the whole document, so polling
    between stages can leave the user waiting minutes. A torch forward pre-hook runs before
    every layer, so inference stops within one layer's runtime. Lazy checkpoint loads run no
    layers; they call :func:`raise_if_cancelled` so a pending cancel stops the next load. If an
    extractor swallows the exception, the next layer raises it again while the request stays set.

    The forward hook only acts on the thread that entered the context, and is skipped when torch
    has not been imported (no model can be running). A missing callback makes everything a no-op.
    """
    if should_cancel is None:
        yield
        return

    token = _cancel_check.set(should_cancel)
    handle = None
    try:
        torch = sys.modules.get("torch")
        if torch is not None:
            owner_thread = threading.get_ident()

            def _raise_if_cancelled(_module: object, _args: object) -> None:
                """Torch forward pre-hook: raise on cancel, but only on the owning thread."""
                if threading.get_ident() == owner_thread:
                    raise_if_cancelled()

            handle = torch.nn.modules.module.register_module_forward_pre_hook(
                _raise_if_cancelled
            )
        yield
    finally:
        if handle is not None:
            handle.remove()
        _cancel_check.reset(token)
