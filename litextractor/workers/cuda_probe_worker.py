"""Background CUDA availability check for application startup."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..extraction_runtime import cuda_available


class CudaAvailabilityWorker(QThread):
    """Probe CUDA without blocking the Qt event loop."""

    availability_checked = Signal(bool)

    def run(self) -> None:
        """Check CUDA availability on the worker thread and emit the result."""
        self.availability_checked.emit(cuda_available())