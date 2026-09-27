# 0010: PDF rendering and the container image

- Status: accepted, with an open question for the maintainer
- Date: 2026-09-27
- Deciders: maintainers

## Context

The brief names WeasyPrint for PDF reports. WeasyPrint is pure Python but loads Pango, HarfBuzz and Fontconfig from the operating system at import time. The application image is distroless (ADR-0002) and has none of them.

The M3 build tried copying exactly the shared libraries WeasyPrint needs (28 libraries from 24 Debian packages, found with `ldd`) into the image, with their dpkg status entries so trivy still sees them. PDF rendering then worked in the image. The trivy gate then failed with 12 high-severity findings, none with a fixed version in Debian 13 at the time:

- `libblkid1` and `libmount1` (util-linux): CVE-2026-76642, CVE-2026-78408, CVE-2026-78409, CVE-2026-78410. Pulled in through GLib's GIO, which Pango links. They concern mount helpers and namespace handling, which a report renderer never calls.
- `libexpat1`: CVE-2026-66046, CVE-2026-76956, CVE-2026-76957, CVE-2026-93990. Fontconfig uses Expat to parse its own configuration files, which are part of the image, not user input.

The findings look unreachable, but the policy in ADR-0005 is that suppressions need maintainer approval, and the brief forbids weakening a gate to get a build through.

## Decision

- The image does not ship Pango for now. The `pdf` renderer checks whether WeasyPrint can load; when it cannot, the package builder uses the `html` renderer, and the package carries `report.html` (the same document, print-ready) instead of `report.pdf`. The manifest records `pdf_rendered: false`, and the reports screen says which format each package has.
- Everywhere Pango is available (developer machines, the CI test job, which installs it), packages carry `report.pdf`, and the tests assert on whichever the environment supports.
- The library-collection script stays in the repository (`deploy/docker/collect-pdf-libs.sh`) so switching PDF on in the image is a two-line Dockerfile change once the question below is answered.

Question for the maintainer, one of:

1. Approve dated trivy suppressions for the eight CVEs above with the reachability statements here, and turn the PDF stage on.
2. Keep the image as it is until Debian ships fixes, then turn the PDF stage on with no suppressions.
3. Render PDFs in a separate, optional renderer image, so the main image stays minimal.

## Consequences

- Packages built in the default image satisfy every check in the brief except the file name `report.pdf`. Auditors can print the HTML report to PDF from any browser; its contents are signed like any other file.
- The HTML report and the PDF come from the same template, so switching PDF on changes no content.
- WeasyPrint and its Python dependencies are still installed in the image. They add no scanner findings and are ready once the native libraries are.
