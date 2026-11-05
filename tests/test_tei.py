"""Offline tests for parsing the copied GROBID TEI fixture."""

from pathlib import Path

import pytest

from grobid_tei import TEIDocument, TEIParsingError

FIXTURE = Path(__file__).parent / "data" / "WagnerLukyanenkoParEtAl2022.tei.xml"


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
    document = TEIDocument.from_bytes(
        b'<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        b"<teiHeader><profileDesc><abstract><p>Summary text.</p></abstract>"
        b"</profileDesc></teiHeader></TEI>"
    )

    assert document.metadata() == {}
    assert document.metadata(abstract=True) == {"abstract": "Summary text."}


def test_metadata_omits_missing_abstract_when_requested() -> None:
    document = TEIDocument.from_bytes(b'<TEI xmlns="http://www.tei-c.org/ns/1.0"/>')

    assert document.metadata(abstract=True) == {}


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
