"""Offline tests for parsing the copied GROBID TEI fixture."""

import json
from pathlib import Path

import pytest

from grobid_tei import TEIDocument, TEIParsingError

FIXTURE = Path(__file__).parent / "data" / "WagnerLukyanenkoParEtAl2022.tei.xml"
METADATA_REFERENCES_FIXTURE = (
    Path(__file__).parent / "data" / "metadata_references.tei.xml"
)
EMPTY_METADATA_FIXTURE = Path(__file__).parent / "data" / "empty_metadata.tei.xml"
ABSTRACT_ONLY_FIXTURE = Path(__file__).parent / "data" / "abstract_only.tei.xml"
REFERENCE_SNAPSHOT = (
    Path(__file__).parent / "data" / "WagnerLukyanenkoParEtAl2022.references.json"
)
GROBID_090_FIXTURE = (
    Path(__file__).parent / "data" / "WagnerLukyanenkoParEtAl2022-grobid-0.9.0.tei.xml"
)
GROBID_090_REFERENCE_SNAPSHOT = (
    Path(__file__).parent
    / "data"
    / "WagnerLukyanenkoParEtAl2022-grobid-0.9.0.references.json"
)


@pytest.fixture
def document() -> TEIDocument:
    return TEIDocument.from_file(FIXTURE)


def test_document_metadata_and_header(document: TEIDocument) -> None:
    assert document.grobid_version() == "0.8.2"
    assert document.metadata() == {
        "entrytype": "misc",
        "author": "Wagner, Gerit and Lukyanenko, Roman and Par, Guy and Paré, Guy",
        "title": "Debates and Perspectives Paper",
        "doi": "10.1177/02683962211048201",
    }
    assert document.metadata(abstract=True) == {
        **document.metadata(),
        "abstract": document.abstract(),
    }
    assert document.abstract() == (
        "Artificial intelligence (AI) is beginning to transform traditional research "
        "practices in many areas. In this context, literature reviews stand out because "
        "they operate on large and rapidly growing volumes of documents, that is, "
        "partially structured (meta)data, and pervade almost every type of paper "
        "published in information systems research or related social science "
        "disciplines. To familiarize researchers with some of the recent trends in this "
        "area, we outline how AI can expedite individual steps of the literature review "
        "process. Considering that the use of AI in this context is in an early stage of "
        "development, we propose a comprehensive research agenda for AI-based literature "
        "reviews (AILRs) in our field. With this agenda, we would like to encourage "
        "design science research and a broader constructive discourse on shaping the "
        "future of AILRs in research."
    )
    assert document.keywords() == [
        "Artificial intelligence",
        "machine learning",
        "natural language processing",
        "research data management",
        "data infrastructure",
        "automation",
        "literature review",
    ]


def test_metadata_can_include_abstract_without_bibliographic_metadata() -> None:
    document = TEIDocument.from_file(ABSTRACT_ONLY_FIXTURE)

    assert document.metadata() == {}
    assert document.metadata(abstract=True) == {"abstract": "Summary text."}


def test_metadata_omits_missing_abstract_when_requested() -> None:
    document = TEIDocument.from_file(EMPTY_METADATA_FIXTURE)

    assert document.metadata(abstract=True) == {}


def test_metadata_extracts_fields_and_omits_absent_optional_fields() -> None:
    document = TEIDocument.from_file(METADATA_REFERENCES_FIXTURE)

    assert document.metadata() == {
        "author": "Example, Alex",
        "title": "Focused Metadata",
        "doi": "10.1234/example",
        "year": "2024",
        "pages": "1--9",
        "entrytype": "misc",
    }
    assert document.metadata(abstract=True) == document.metadata()


def test_authors_and_references(document: TEIDocument) -> None:
    authors = document.author_details()
    assert authors[:3] == [
        {"forename": "Gerit", "surname": "Wagner"},
        {"forename": "Roman", "surname": "Lukyanenko"},
        {
            "forename": "Guy",
            "surname": "Par",
            "email": "guy.pare@hec.ca",
            "orcid": "0000-0001-7425-1994",
        },
    ]

    references = document.references(include_citation_counts=True)
    first = references[0]
    assert first.tei_id == "b0"
    assert first.in_text_citation_count == 1
    assert first["entrytype"] == "article"
    assert first["author"] == "Adams, C. E and Polzmacher, S. and Wolff, A."
    assert (
        first["title"]
        == "Systematic reviews: work that needs to be done and not to be done"
    )
    assert first["journal"] == "Journal of Evidence-Based Medicine"
    assert "tei_id" not in first.fields
    assert "in_text_citation_count" not in first.fields


def test_reference_extraction_fields_types_and_partial_metadata() -> None:
    document = TEIDocument.from_file(METADATA_REFERENCES_FIXTURE)
    references_by_id = {
        reference.tei_id: reference
        for reference in document.references(include_citation_counts=True)
    }

    article = references_by_id["b-article"]
    assert article.fields == {
        "author": "Doe, J.",
        "title": "An article title",
        "doi": "10.5678/article",
        "year": "2021",
        "pages": "100--108",
        "number": "3",
        "volume": "12",
        "entrytype": "article",
        "journal": "Journal of Examples",
    }
    assert article.in_text_citation_count == 2

    book = references_by_id["b-book"]
    assert book["entrytype"] == "book"
    assert book["title"] == "A Useful Book"
    assert book["author"] == "Smith,"
    assert book["pages"] == "7"
    assert "year" not in book
    assert book.in_text_citation_count == 0

    proceedings = references_by_id["b-proceedings"]
    assert proceedings["entrytype"] == "inproceedings"
    assert proceedings["title"] == "A Conference Paper"
    assert proceedings["booktitle"] == "Proceedings of Example Conference"
    assert proceedings["year"] == "2022"
    assert proceedings["pages"] == "44-51"
    assert proceedings.in_text_citation_count == 1

    partial = references_by_id["b-partial"]
    assert partial.fields == {
        "title": "A Partial Reference",
        "pages": "9",
        "entrytype": "misc",
    }
    assert partial.in_text_citation_count == 0


def test_reference_citation_counts_are_optional() -> None:
    document = TEIDocument.from_file(METADATA_REFERENCES_FIXTURE)
    article = next(
        reference
        for reference in document.references()
        if reference.tei_id == "b-article"
    )

    assert article.in_text_citation_count is None


def test_full_reference_extraction_snapshot() -> None:
    """Compare every generic reference field and citation count by TEI ID."""
    document = TEIDocument.from_file(FIXTURE)
    references = document.references(include_citation_counts=True)
    actual = {
        reference.tei_id: {
            "fields": dict(reference.fields),
            "in_text_citation_count": reference.in_text_citation_count,
        }
        for reference in references
    }
    expected = json.loads(REFERENCE_SNAPSHOT.read_text())

    assert len(actual) == 120
    assert actual == expected


def test_grobid_090_full_reference_extraction_snapshot() -> None:
    """Cover the complete reference output from the checked-in GROBID 0.9.0 TEI."""
    document = TEIDocument.from_file(GROBID_090_FIXTURE)
    assert document.grobid_version() == "0.9.0"
    assert document.metadata() == {
        "author": (
            "Wagner, Gerit and Lukyanenko, Roman and Par, Guy and Paré, Guy "
            "and Id, Orcid"
        ),
        "title": "Artificial intelligence and the conduct of literature reviews",
        "doi": "10.1177/02683962211048201",
        "entrytype": "misc",
    }

    actual = {
        reference.tei_id: {
            "in_text_citation_count": reference.in_text_citation_count,
            "fields": dict(reference.fields),
        }
        for reference in document.references(include_citation_counts=True)
    }
    expected = json.loads(GROBID_090_REFERENCE_SNAPSHOT.read_text())

    assert len(actual) == 120
    assert actual == expected
    assert actual["b0"]["fields"]["entrytype"] == "article"
    assert actual["b0"]["in_text_citation_count"] == 1
    assert actual["b6"]["fields"]["entrytype"] == "article"
    assert actual["b6"]["fields"]["journal"] == "Organizational Research Methods"
    assert actual["b6"]["in_text_citation_count"] == 2


def test_section_citations_paragraphs_and_annotation(document: TEIDocument) -> None:
    citations = document.citations_by_section()
    assert citations["introduction"][:4] == ["b0", "b108", "b50", "b45"]
    assert next(document.iter_paragraphs()).startswith(
        "The potential of artificial intelligence (AI) to augment and partially automate research"
    )

    document.annotate_reference_ids({"b0": "local-0"})
    serialized = document.to_bytes()
    assert b'<biblStruct xml:id="b0" ID="local-0">' in serialized
    assert b'<ref type="bibr" target="#b0" ID="local-0">' in serialized


def test_bytes_round_trip_and_fixture_is_unchanged() -> None:
    before = FIXTURE.read_bytes()
    document = TEIDocument.from_bytes(before)
    assert TEIDocument.from_bytes(document.to_bytes()).metadata() == document.metadata()
    assert FIXTURE.read_bytes() == before


@pytest.mark.parametrize(
    "xml",
    [
        b"[BAD_INPUT_DATA]",
        b"<TEI><unclosed>",
        b"<!DOCTYPE x [<!ENTITY e 'x'>]><x>&e;</x>",
    ],
)
def test_invalid_or_unsafe_xml_raises_package_exception(xml: bytes) -> None:
    with pytest.raises(TEIParsingError):
        TEIDocument.from_bytes(xml)
