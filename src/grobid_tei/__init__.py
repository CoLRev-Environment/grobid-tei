"""Reusable client and parser for GROBID TEI documents."""

from grobid_tei.client import GrobidClient
from grobid_tei.exceptions import GrobidServiceError
from grobid_tei.exceptions import GrobidTEIError
from grobid_tei.exceptions import TEIParsingError
from grobid_tei.tei import TEIDocument
from grobid_tei.tei import TEIReference

__all__ = [
    "GrobidClient",
    "GrobidServiceError",
    "GrobidTEIError",
    "TEIDocument",
    "TEIParsingError",
    "TEIReference",
]
