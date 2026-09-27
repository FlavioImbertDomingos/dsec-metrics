"""``pdf`` renderer: the HTML report through WeasyPrint.

WeasyPrint needs Pango, HarfBuzz and Fontconfig from the operating system. The default
container image does not ship them yet (ADR-0010), so ``available()`` is False there and
the package builder includes the HTML report instead.
"""

from __future__ import annotations

import contextlib
import io
from functools import cache
from typing import TYPE_CHECKING, Any, ClassVar

from dsec_metrics.plugins.sdk.renderer import Renderer, RendererUnavailableError
from dsec_metrics.reports.html import render_html

if TYPE_CHECKING:
    from dsec_metrics.reports.data import ReportData


@cache
def _weasyprint() -> Any:
    """WeasyPrint, or None when its native libraries are missing. Imported on first use,
    because importing loads Pango; the banner WeasyPrint prints on failure is swallowed."""
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            import weasyprint
    except OSError:
        return None
    return weasyprint


def _refuse(url: str, *args: object, **kwargs: object) -> dict[str, object]:
    """Reports load nothing from outside the template: no network, no local files."""
    raise ValueError(f"report rendering does not fetch {url[:64]}")


class PdfRenderer(Renderer):
    """Report as PDF with cover, contents, page numbers and appendix."""

    name = "pdf"
    version = "1.0.0"
    media_types: ClassVar[dict[str, str]] = {"pdf": "application/pdf"}

    def available(self) -> bool:
        return _weasyprint() is not None

    def render(self, data: ReportData) -> dict[str, bytes]:
        weasyprint = _weasyprint()
        if weasyprint is None:
            raise RendererUnavailableError("WeasyPrint cannot load Pango; PDF rendering is off")
        html = render_html(data)
        document = weasyprint.HTML(string=html, url_fetcher=_refuse)
        pdf: bytes = document.write_pdf()
        return {"report.pdf": pdf}


class HtmlRenderer(Renderer):
    """The same report as a standalone HTML file."""

    name = "html"
    version = "1.0.0"
    media_types: ClassVar[dict[str, str]] = {"html": "text/html"}

    def render(self, data: ReportData) -> dict[str, bytes]:
        return {"report.html": render_html(data).encode("utf-8")}
