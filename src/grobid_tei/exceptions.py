"""Exceptions raised by :mod:`grobid_tei`."""


class GrobidTEIError(Exception):
    """Base class for errors raised by this package."""


class GrobidServiceError(GrobidTEIError):
    """A GROBID service request failed or returned an unusable response."""


class IncompatibleGrobidVersionError(GrobidTEIError):
    """The GROBID service reports a version known to be incompatible."""

    def __init__(self, version: str) -> None:
        self.version = version
        super().__init__(
            f"GROBID version {version!r} is known to be incompatible with grobid-tei"
        )


class TEIParsingError(GrobidTEIError):
    """TEI XML could not be parsed safely or was not valid XML."""
