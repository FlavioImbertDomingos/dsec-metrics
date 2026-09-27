"""Base class for report renderers (entry point group ``dsec_metrics.renderers``)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from dsec_metrics.reports.data import ReportData


class RendererUnavailableError(RuntimeError):
    """The renderer cannot run here, for example because a system library is missing."""


class Renderer(ABC):
    """Turns report data into one or more files for the package."""

    name: ClassVar[str]
    version: ClassVar[str]
    media_types: ClassVar[dict[str, str]]  # file extension -> media type

    def available(self) -> bool:
        """False when the renderer cannot run in this environment."""
        return True

    @abstractmethod
    def render(self, data: ReportData) -> dict[str, bytes]:
        """Package path -> file contents."""
