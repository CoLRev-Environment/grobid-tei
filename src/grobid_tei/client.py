"""HTTP client for a separately managed GROBID service."""

from __future__ import annotations

import math
import warnings
from pathlib import Path
from urllib.parse import urlsplit

import requests

from grobid_tei.exceptions import GrobidServiceError, IncompatibleGrobidVersionError

_TESTED_GROBID_VERSIONS = frozenset({"0.8.2"})
_INCOMPATIBLE_GROBID_VERSIONS: frozenset[str] = frozenset()


class GrobidClient:
    """Call a GROBID server at an explicitly configured URL.

    The client does not start, stop, or otherwise manage the server process.
    """

    def __init__(self, *, service_url: str, timeout: float = 180.0) -> None:
        if not service_url or not isinstance(service_url, str):
            raise ValueError("service_url must be a non-empty HTTP(S) URL")
        parsed_url = urlsplit(service_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("service_url must be a non-empty HTTP(S) URL")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a positive finite number")

        self.service_url = service_url.rstrip("/")
        self.timeout = float(timeout)

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
        """Return the version reported by the configured GROBID server."""
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
        return version

    def check_compatibility(self) -> str:
        """Check the server version before processing and return that version.

        Known-incompatible versions raise :class:`IncompatibleGrobidVersionError`.
        Versions not yet tested with this package emit a warning and are allowed.
        This check is opt-in; it is not performed by :meth:`process_fulltext`.
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
