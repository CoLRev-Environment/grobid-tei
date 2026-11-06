"""HTTP client for a separately managed GROBID service."""

from __future__ import annotations

import math
import warnings
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

import requests

from grobid_tei.exceptions import GrobidServiceError, IncompatibleGrobidVersionError

_TESTED_GROBID_VERSIONS = frozenset({"0.8.2"})
_INCOMPATIBLE_GROBID_VERSIONS: frozenset[str] = frozenset()


class GrobidClient:
    """Call a GROBID server at an explicitly configured URL.

    The client does not start, stop, or otherwise manage the server process.
    By default, the server version is retrieved during initialization and
    cached for this client instance. Set ``skip_version=True`` to defer lookup.
    """

    def __init__(
        self,
        *,
        service_url: str,
        timeout: float = 180.0,
        skip_version: bool = False,
    ) -> None:
        if not service_url or not isinstance(service_url, str):
            raise ValueError("service_url must be a non-empty HTTP(S) URL")
        parsed_url = urlsplit(service_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("service_url must be a non-empty HTTP(S) URL")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a positive finite number")

        self.service_url = service_url.rstrip("/")
        self.timeout = float(timeout)
        self._grobid_version: str | None = None
        if not skip_version:
            self.version()

    def is_available(self) -> bool:
        """Return whether the configured GROBID server reports itself alive."""
        try:
            response = requests.get(
                f"{self.service_url}/api/isalive", timeout=self.timeout
            )
            return response.ok and response.text.strip().lower() == "true"
        except requests.RequestException:
            return False

    def version(self) -> str:
        """Return the cached version, retrieving it once if needed."""
        if self._grobid_version is not None:
            return self._grobid_version

        try:
            response = requests.get(
                f"{self.service_url}/api/version", timeout=self.timeout
            )
            response.raise_for_status()
            version = response.json().get("version")
        except (requests.RequestException, ValueError, AttributeError) as exc:
            raise GrobidServiceError(
                f"Could not retrieve GROBID version from {self.service_url}: {exc}"
            ) from exc

        if not isinstance(version, str) or not version:
            raise GrobidServiceError(
                f"GROBID returned no version from {self.service_url}"
            )
        self._grobid_version = version
        return version

    def check_compatibility(self) -> str:
        """Check the server version before processing and return that version.

        Known-incompatible versions raise :class:`IncompatibleGrobidVersionError`.
        Versions not yet tested with this package emit a warning and are allowed.
        This check is opt-in; it is not performed by processing methods.
        The version lookup reuses the value cached during initialization, if any.
        """
        version = self.version()
        if version in _INCOMPATIBLE_GROBID_VERSIONS:
            raise IncompatibleGrobidVersionError(version)
        if version not in _TESTED_GROBID_VERSIONS:
            warnings.warn(
                f"GROBID version {version!r} has not been tested with grobid-tei; "
                "processing will be attempted",
                UserWarning,
                stacklevel=2,
            )
        return version

    def process_fulltext(
        self,
        pdf_path: Path,
        *,
        consolidate_header: bool = False,
        consolidate_citations: bool = False,
    ) -> bytes:
        """Submit a PDF to GROBID and return the resulting TEI XML bytes."""
        path = Path(pdf_path)
        if not path.is_file():
            raise FileNotFoundError(path)

        options = {
            "consolidateHeader": "1" if consolidate_header else "0",
            "consolidateCitations": "1" if consolidate_citations else "0",
        }
        try:
            with path.open("rb") as pdf_file:
                response = requests.post(
                    f"{self.service_url}/api/processFulltextDocument",
                    files={"input": (path.name, pdf_file, "application/pdf")},
                    data=options,
                    timeout=self.timeout,
                )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise GrobidServiceError(
                f"GROBID full-text processing failed at {self.service_url}: {exc}"
            ) from exc

        return response.content

    def process_citation(
        self, citation: str, *, consolidate_citations: bool = False
    ) -> bytes:
        """Parse one raw bibliographical citation and return TEI XML bytes."""
        if not isinstance(citation, str):
            raise TypeError("citation must be a non-empty string")
        if not citation.strip():
            raise ValueError("citation must be a non-empty string")

        options = {
            "citations": citation,
            "consolidateCitations": "1" if consolidate_citations else "0",
        }
        try:
            response = requests.post(
                f"{self.service_url}/api/processCitation",
                data=options,
                headers={"Accept": "application/xml"},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise GrobidServiceError(
                f"GROBID citation processing failed at {self.service_url}: {exc}"
            ) from exc

        return response.content

    def process_citation_list(
        self, citations: Sequence[str], *, consolidate_citations: bool = False
    ) -> bytes:
        """Parse multiple raw bibliographical citations and return TEI XML bytes."""
        if isinstance(citations, (str, bytes)) or not isinstance(citations, Sequence):
            raise TypeError("citations must be a non-empty sequence of strings")
        if not citations:
            raise ValueError("citations must be a non-empty sequence of strings")

        form_data: list[tuple[str, str]] = []
        for citation in citations:
            if not isinstance(citation, str):
                raise TypeError("each citation must be a non-empty string")
            if not citation.strip():
                raise ValueError("each citation must be a non-empty string")
            form_data.append(("citations", citation))
        form_data.append(
            ("consolidateCitations", "1" if consolidate_citations else "0")
        )

        try:
            response = requests.post(
                f"{self.service_url}/api/processCitationList",
                data=form_data,
                headers={"Accept": "application/xml"},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise GrobidServiceError(
                f"GROBID citation list processing failed at {self.service_url}: {exc}"
            ) from exc

        return response.content
