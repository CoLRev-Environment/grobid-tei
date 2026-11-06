"""HTTP client tests using mocked responses; no GROBID service is required."""

import warnings
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

from grobid_tei import (
    GrobidClient,
    GrobidServiceError,
    IncompatibleGrobidVersionError,
    TEIDocument,
)


def test_explicit_service_url_and_availability() -> None:
    client = GrobidClient(service_url="http://grobid.example:8070/", timeout=12)
    response = Mock(ok=True, text="true\n")
    with patch("grobid_tei.client.requests.get", return_value=response) as get:
        assert client.is_available()
    get.assert_called_once_with("http://grobid.example:8070/api/isalive", timeout=12.0)


def test_availability_reports_connection_failure_as_false() -> None:
    client = GrobidClient(service_url="https://grobid.example")
    with patch("grobid_tei.client.requests.get", side_effect=requests.ConnectionError):
        assert not client.is_available()


def test_version() -> None:
    client = GrobidClient(service_url="http://grobid.example")
    response = Mock()
    response.json.return_value = {"version": "0.8.2"}
    with patch("grobid_tei.client.requests.get", return_value=response) as get:
        assert client.version() == "0.8.2"
    get.assert_called_once_with("http://grobid.example/api/version", timeout=180.0)


def test_version_errors_are_package_exceptions() -> None:
    client = GrobidClient(service_url="http://grobid.example")
    with patch(
        "grobid_tei.client.requests.get",
        side_effect=requests.ConnectionError("offline"),
    ):
        with pytest.raises(GrobidServiceError, match="Could not retrieve"):
            client.version()


def test_compatibility_check_accepts_tested_version_without_warning() -> None:
    client = GrobidClient(service_url="http://grobid.example")
    with patch.object(client, "version", return_value="0.8.2"):
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            assert client.check_compatibility() == "0.8.2"
    assert not recorded


def test_compatibility_check_warns_but_allows_untested_version() -> None:
    client = GrobidClient(service_url="http://grobid.example")
    with patch.object(client, "version", return_value="0.9.0"):
        with pytest.warns(UserWarning, match="has not been tested"):
            assert client.check_compatibility() == "0.9.0"


def test_compatibility_check_rejects_known_incompatible_version(monkeypatch) -> None:
    import grobid_tei.client as client_module

    monkeypatch.setattr(
        client_module, "_INCOMPATIBLE_GROBID_VERSIONS", frozenset({"0.7.0"})
    )
    client = GrobidClient(service_url="http://grobid.example")
    with patch.object(client, "version", return_value="0.7.0"):
        with pytest.raises(IncompatibleGrobidVersionError) as error:
            client.check_compatibility()
    assert error.value.version == "0.7.0"


def test_process_fulltext_posts_pdf_and_options(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.7 sample")
    response = Mock(content=b"<TEI/>")
    client = GrobidClient(service_url="http://grobid.example", timeout=25)

    with patch("grobid_tei.client.requests.post", return_value=response) as post:
        assert (
            client.process_fulltext(
                pdf, consolidate_header=True, consolidate_citations=False
            )
            == b"<TEI/>"
        )

    args, kwargs = post.call_args
    assert args == ("http://grobid.example/api/processFulltextDocument",)
    assert kwargs["data"] == {"consolidateHeader": "1", "consolidateCitations": "0"}
    assert kwargs["timeout"] == 25.0
    upload_name, upload_file, content_type = kwargs["files"]["input"]
    assert upload_name == "paper.pdf"
    assert upload_file.closed
    assert content_type == "application/pdf"


def test_process_fulltext_service_error_and_missing_file(tmp_path: Path) -> None:
    client = GrobidClient(service_url="http://grobid.example")
    with pytest.raises(FileNotFoundError):
        client.process_fulltext(tmp_path / "missing.pdf")

    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"pdf")
    with patch(
        "grobid_tei.client.requests.post", side_effect=requests.Timeout("timed out")
    ):
        with pytest.raises(GrobidServiceError, match="processing failed"):
            client.process_fulltext(pdf)


def test_process_citation_posts_form_and_returns_parseable_tei() -> None:
    citation_xml = (
        b"<biblStruct><analytic><title/><author><persName "
        b'xmlns="http://www.tei-c.org/ns/1.0"><surname>Graff</surname>'
        b'</persName></author></analytic><monogr><title level="j">'
        b"Expert. Opin. Ther. Targets</title><imprint>"
        b'<biblScope unit="volume">6</biblScope>'
        b'<biblScope unit="issue">1</biblScope>'
        b'<biblScope unit="page" from="103" to="113"/>'
        b'<date type="published" when="2002"/>'
        b"</imprint></monogr></biblStruct>"
    )
    response = Mock(content=citation_xml)
    client = GrobidClient(service_url="http://grobid.example/", timeout=25)

    with patch("grobid_tei.client.requests.post", return_value=response) as post:
        assert (
            client.process_citation(
                "Graff, Expert. Opin. Ther. Targets (2002) 6(1): 103-113",
                consolidate_citations=True,
            )
            == citation_xml
        )

    args, kwargs = post.call_args
    assert args == ("http://grobid.example/api/processCitation",)
    assert kwargs["data"] == {
        "citations": "Graff, Expert. Opin. Ther. Targets (2002) 6(1): 103-113",
        "consolidateCitations": "1",
    }
    assert kwargs["headers"] == {"Accept": "application/xml"}
    assert kwargs["timeout"] == 25.0

    references = TEIDocument.from_bytes(citation_xml).references()
    assert len(references) == 1
    assert references[0]["author"] == "Graff,"
    assert references[0]["journal"] == "Expert. Opin. Ther. Targets"
    assert references[0]["year"] == "2002"
    assert references[0]["pages"] == "103--113"


def test_process_citation_defaults_to_no_consolidation() -> None:
    client = GrobidClient(service_url="http://grobid.example")
    response = Mock(content=b"<biblStruct/>")

    with patch("grobid_tei.client.requests.post", return_value=response) as post:
        client.process_citation("A. Author, A. Citation, 2024")

    assert post.call_args.kwargs["data"]["consolidateCitations"] == "0"


@pytest.mark.parametrize("citation", ["", " \t\n"])
def test_process_citation_rejects_empty_input(citation: str) -> None:
    client = GrobidClient(service_url="http://grobid.example")
    with pytest.raises(ValueError, match="citation must be a non-empty string"):
        client.process_citation(citation)


@pytest.mark.parametrize("citation", [None, 42])
def test_process_citation_rejects_non_string_input(citation: object) -> None:
    client = GrobidClient(service_url="http://grobid.example")
    with pytest.raises(TypeError, match="citation must be a non-empty string"):
        client.process_citation(citation)  # type: ignore[arg-type]


def test_process_citation_service_errors() -> None:
    client = GrobidClient(service_url="http://grobid.example")
    with (
        patch(
            "grobid_tei.client.requests.post",
            side_effect=requests.ConnectionError("offline"),
        ),
        pytest.raises(GrobidServiceError, match="citation processing failed"),
    ):
        client.process_citation("A. Author, A. Citation, 2024")

    response = Mock()
    response.raise_for_status.side_effect = requests.HTTPError("503 unavailable")
    with (
        patch("grobid_tei.client.requests.post", return_value=response),
        pytest.raises(GrobidServiceError, match="503 unavailable"),
    ):
        client.process_citation("A. Author, A. Citation, 2024")


@pytest.mark.parametrize("url", ["", "localhost:8070", "ftp://example.org", "/api"])
def test_invalid_service_url_is_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        GrobidClient(service_url=url)
