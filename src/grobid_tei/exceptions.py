"""Exceptions raised by :mod:`grobid_tei`."""


class GrobidTEIError(Exception):
    """Base class for errors raised by this package."""


class GrobidServiceError(GrobidTEIError):
    """A GROBID service request failed or returned an unusable response."""


class TEIParsingError(GrobidTEIError):
    """TEI XML could not be parsed safely or was not valid XML."""
