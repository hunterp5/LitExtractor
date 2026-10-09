"""Scoped crop-margin policy shared by extraction and OpenChemIE adapters."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

DEFAULT_MOLECULE_CROP_MARGIN = 0.0
DEFAULT_LAYOUT_CONTEXT_MARGIN = 0.08

_molecule_crop_margin: ContextVar[float] = ContextVar(
    "patentextractor_molecule_crop_margin",
    default=DEFAULT_MOLECULE_CROP_MARGIN,
)


def current_molecule_crop_margin() -> float:
    """Return the molecule-crop margin active in this execution context."""
    return _molecule_crop_margin.get()


@contextmanager
def use_molecule_crop_margin(margin_fraction: float) -> Iterator[None]:
    """Temporarily apply a molecule-crop margin without changing global state."""
    margin = max(0.0, float(margin_fraction))
    token = _molecule_crop_margin.set(margin)
    try:
        yield
    finally:
        _molecule_crop_margin.reset(token)
