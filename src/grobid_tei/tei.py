"""Read and annotate TEI documents produced by GROBID."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias
from xml.etree.ElementTree import Element, register_namespace

from defusedxml import ElementTree as DefusedET
from defusedxml.common import DefusedXmlException

from grobid_tei.exceptions import TEIParsingError

TEI_NAMESPACE = "http://www.tei-c.org/ns/1.0"
XML_NAMESPACE = "http://www.w3.org/XML/1998/namespace"
_TEI = f"{{{TEI_NAMESPACE}}}"
_XML_ID = f"{{{XML_NAMESPACE}}}id"
_TextMapping: TypeAlias = Mapping[str, str]


@dataclass(frozen=True)
class TEIReference(Mapping[str, str]):
    """A bibliography entry with generic fields and its TEI-specific identity.

    Bibliographic values are available in ``bibliographic_fields`` (also
    exposed as ``fields``) and by mapping-style access, e.g.
    ``reference["title"]``. The TEI ``xml:id`` and optional in-text citation
    count are separate attributes rather than bibliographic fields.
    """

    bibliographic_fields: _TextMapping
    tei_id: str | None = None
    in_text_citation_count: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "bibliographic_fields",
            MappingProxyType(dict(self.bibliographic_fields)),
        )

    @property
    def fields(self) -> _TextMapping:
        """Alias for the generic bibliographic field mapping."""
        return self.bibliographic_fields

    def __getitem__(self, key: str) -> str:
        return self.bibliographic_fields[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.bibliographic_fields)

    def __len__(self) -> int:
        return len(self.bibliographic_fields)


class TEIDocument:
    """A parsed TEI XML document.

    Use :meth:`from_bytes` or :meth:`from_file` to construct a document.
    XML is parsed with ``defusedxml`` to reject unsafe entity declarations.
    """

    def __init__(self, root: Element) -> None:
        self._root = root

    @classmethod
    def from_bytes(cls, xml: bytes) -> TEIDocument:
        """Parse a document from TEI XML bytes."""
        if not isinstance(xml, bytes):
            raise TypeError("xml must be bytes")
        if b"[BAD_INPUT_DATA]" in xml[:256]:
            raise TEIParsingError("GROBID reported bad input data")
        if b"[TIMEOUT]" in xml[:256]:
            raise TEIParsingError("GROBID reported a processing timeout")
        try:
            root = DefusedET.fromstring(xml)
        except (DefusedXmlException, DefusedET.ParseError, ValueError) as exc:
            raise TEIParsingError(f"Could not parse TEI XML: {exc}") from exc
        if root.tag == "biblStruct":
            for node in root.iter():
                if not node.tag.startswith("{"):
                    node.tag = _TEI + node.tag
        return cls(root)

    @classmethod
    def from_file(cls, path: Path) -> TEIDocument:
        """Read and parse a TEI XML file."""
        file_path = Path(path)
        try:
            xml = file_path.read_bytes()
        except OSError:
            raise
        return cls.from_bytes(xml)

    def to_bytes(self) -> bytes:
        """Serialize the current document as UTF-8 XML bytes."""
        register_namespace("", TEI_NAMESPACE)
        return DefusedET.tostring(self._root, encoding="utf-8")

    def grobid_version(self) -> str | None:
        """Return the GROBID version recorded in the TEI header, if present."""
        application = self._root.find(
            f".//{_TEI}encodingDesc/{_TEI}appInfo/{_TEI}application"
        )
        if application is None:
            application = self._root.find(f".//{_TEI}application")
        return application.get("version") if application is not None else None

    def metadata(self, *, abstract: bool = False) -> dict[str, str]:
        """Extract document-level bibliographic metadata.

        Keys are generic lowercase bibliography names such as ``title``,
        ``author``, ``doi``, and ``entrytype``. Set ``abstract=True`` to include
        the abstract under the ``abstract`` key when present.
        """
        source = self._root.find(f".//{_TEI}sourceDesc/{_TEI}biblStruct")
        fields = (
            self._bibliographic_fields(source, document=True)
            if source is not None
            else {}
        )
        title = fields.get("title")
        if title:
            for suffix in (
                "(Completed paper)",
                "(Completed-paper)",
                "(Research-in-Progress)",
                "Completed Research Paper",
            ):
                title = title.replace(suffix, "")
            fields["title"] = title
        metadata = {
            key: self._clean_value(value)
            for key, value in fields.items()
            if self._clean_value(value)
        }
        if abstract and (abstract_text := self.abstract()):
            metadata["abstract"] = abstract_text
        return metadata

    def abstract(self) -> str | None:
        """Return the abstract text, or ``None`` if the document has none."""
        node = self._root.find(f".//{_TEI}profileDesc/{_TEI}abstract")
        if node is None:
            return None
        text = self._normalized_text(node)
        return text or None

    def keywords(self) -> list[str]:
        """Return keywords in document order."""
        return [
            text
            for term in self._root.iter(f"{_TEI}term")
            if (text := self._normalized_text(term))
        ]

    def author_details(self) -> list[dict[str, str]]:
        """Return structured author names and available contact identifiers."""
        source = self._root.find(f".//{_TEI}sourceDesc")
        if source is None:
            return []
        analytic = source.find(f".//{_TEI}analytic")
        if analytic is None:
            return []

        details: list[dict[str, str]] = []
        for author in analytic.findall(_TEI + "author"):
            person = author.find(_TEI + "persName")
            if person is None:
                continue
            item: dict[str, str] = {}
            for key, node_name in (
                ("surname", "surname"),
                ("forename", 'forename[@type="first"]'),
                ("middlename", 'forename[@type="middle"]'),
            ):
                node = person.find(f"{_TEI}{node_name}")
                value = self._normalized_text(node) if node is not None else ""
                if value:
                    item[key] = value
            email = author.find(_TEI + "email")
            if email is not None and (value := self._normalized_text(email)):
                item["email"] = value
            orcid = author.find(f'{_TEI}idno[@type="ORCID"]')
            if orcid is not None and (value := self._normalized_text(orcid)):
                item["orcid"] = value
            details.append(item)
        return details

    def references(
        self, *, include_citation_counts: bool = False
    ) -> list[TEIReference]:
        """Return bibliography entries in document order.

        The GROBID ``xml:id`` is exposed as ``TEIReference.tei_id``. When
        requested, counts of in-text ``<ref target="#tei-id">`` links are
        exposed as ``TEIReference.in_text_citation_count``.
        """
        references: list[TEIReference] = []
        if self._root.tag == _TEI + "biblStruct":
            reference_nodes = [self._root]
        else:
            reference_nodes = [
                node
                for bibliography in self._root.iter(f"{_TEI}listBibl")
                for node in bibliography
            ]
        for node in reference_nodes:
            fields = self._bibliographic_fields(node)
            tei_id = node.get(_XML_ID)
            citation_count = None
            if include_citation_counts:
                citation_count = self._citation_count(tei_id) if tei_id else 0
            references.append(
                TEIReference(
                    bibliographic_fields=fields,
                    tei_id=tei_id,
                    in_text_citation_count=citation_count,
                )
            )
        return references

    def citations_by_section(self) -> dict[str, list[str]]:
        """Map lowercased section headings to referenced TEI IDs."""
        parent_map = {child: parent for parent in self._root.iter() for child in parent}
        result: dict[str, list[str]] = {}
        for heading in self._root.iter(f"{_TEI}head"):
            section_name = self._normalized_text(heading).lower()
            parent = parent_map.get(heading)
            if not section_name or parent is None:
                continue
            citation_ids = [
                target[1:]
                for ref in parent.iter(f"{_TEI}ref")
                if ref.get("type") == "bibr"
                and (target := ref.get("target", "")).startswith("#")
            ]
            if citation_ids:
                result[section_name] = citation_ids
        return result

    def iter_paragraphs(
        self,
        *,
        min_chars: int = 40,
        exclude_sections: tuple[str, ...] = (
            "references",
            "reference",
            "bibliography",
            "acknowledgment",
            "acknowledgement",
            "appendix",
        ),
    ) -> Iterator[str]:
        """Iterate over cleaned body paragraphs in reading order.

        Paragraphs shorter than ``min_chars`` and paragraphs inside reference
        lists, notes, figures, tables, or named excluded sections are skipped.
        """
        text_node = self._root.find(f".//{_TEI}text")
        if text_node is None:
            return
        body = text_node.find(_TEI + "body")
        if body is None:
            body = text_node
        parent_map = {child: parent for parent in body.iter() for child in parent}
        excluded = {name.casefold() for name in exclude_sections}

        def paragraph_is_excluded(paragraph: Element) -> bool:
            current = paragraph
            while current in parent_map:
                current = parent_map[current]
                if current.tag in {
                    _TEI + "listBibl",
                    _TEI + "note",
                    _TEI + "figure",
                    _TEI + "table",
                }:
                    return True
                heading = current.find(_TEI + "head")
                if (
                    heading is not None
                    and self._normalized_text(heading).casefold() in excluded
                ):
                    return True
            return False

        for paragraph in body.iter(_TEI + "p"):
            if paragraph_is_excluded(paragraph):
                continue
            text = self._normalized_text(paragraph)
            if len(text) >= min_chars:
                yield text

    def annotate_reference_ids(self, record_ids_by_tei_id: Mapping[str, str]) -> None:
        """Attach caller-provided IDs to bibliography entries and citations.

        Each matching bibliography ``<biblStruct>`` and in-text ``<ref>`` gets
        an unqualified ``ID`` attribute. This method performs only the supplied
        mapping; it does not decide how references should be matched.
        """
        if not record_ids_by_tei_id:
            return
        for bibliography in self._root.iter(f"{_TEI}listBibl"):
            for reference in bibliography:
                tei_id = reference.get(_XML_ID)
                record_id = record_ids_by_tei_id.get(tei_id) if tei_id else None
                if record_id is not None:
                    reference.set("ID", record_id)

        for citation in self._root.iter(f"{_TEI}ref"):
            target = citation.get("target", "")
            tei_id = target[1:] if target.startswith("#") else ""
            record_id = record_ids_by_tei_id.get(tei_id)
            if record_id is not None:
                citation.set("ID", record_id)

    def _bibliographic_fields(
        self, reference: Element, *, document: bool = False
    ) -> dict[str, str]:
        analytic = reference.find(_TEI + "analytic")
        monograph = reference.find(_TEI + "monogr")
        fields: dict[str, str] = {}

        author_container = analytic if analytic is not None else monograph
        if author_container is not None:
            authors = [
                name
                for author in author_container.findall(_TEI + "author")
                if (name := self._author_name(author))
            ]
            if authors:
                fields["author"] = " and ".join(authors)

        title_container = analytic if analytic is not None else monograph
        title = self._first_title(title_container)
        if title:
            fields["title"] = title

        doi = ""
        for idno in reference.findall(f'.//{_TEI}idno[@type="DOI"]'):
            if value := self._normalized_text(idno):
                doi = value
        if doi:
            fields["doi"] = doi

        imprint = monograph.find(_TEI + "imprint") if monograph is not None else None
        if imprint is not None:
            date = imprint.find(_TEI + "date")
            if date is not None:
                year = date.get("when", "")
                match = re.match(r"\d{4}", year)
                if match:
                    fields["year"] = match.group(0)
            pages = imprint.findall(f'{_TEI}biblScope[@unit="page"]')
            page_values = []
            for page in pages:
                start = page.get("from", "")
                end = page.get("to", "")
                value = (
                    f"{start}--{end}"
                    if start and end
                    else start or end or self._normalized_text(page)
                )
                if value:
                    page_values.append(value)
            if page_values:
                fields["pages"] = (
                    "--".join(page_values) if len(page_values) > 1 else page_values[0]
                )
            for unit, key in (("issue", "number"), ("volume", "volume")):
                node = imprint.find(f'{_TEI}biblScope[@unit="{unit}"]')
                if node is not None and (value := self._normalized_text(node)):
                    fields[key] = value

        if document:
            fields["entrytype"] = "misc"
        else:
            entrytype = self._entrytype(reference)
            fields["entrytype"] = entrytype
            if entrytype == "article":
                journal = self._monograph_title(monograph)
                if journal:
                    fields["journal"] = journal
            elif entrytype == "book":
                monograph_title = self._monograph_title(monograph)
                if monograph_title:
                    fields["title"] = monograph_title
            elif entrytype == "inproceedings":
                booktitle = self._monograph_title(monograph)
                if booktitle:
                    fields["booktitle"] = booktitle
        return {key: self._clean_value(value) for key, value in fields.items() if value}

    def _entrytype(self, reference: Element) -> str:
        monograph = reference.find(_TEI + "monogr")
        if monograph is None:
            return "misc"
        if monograph.find(_TEI + "meeting") is not None:
            return "inproceedings"
        title = monograph.find(_TEI + "title")
        if title is None:
            return "misc"
        title_text = self._normalized_text(title).casefold()
        if any(
            word in title_text
            for word in ("conference", "proceedings", "symposium", "meeting")
        ):
            return "inproceedings"
        level = title.get("level", "")
        if level == "j":
            return "article"
        if level in {"m", "s"}:
            return "book"
        return "misc"

    def _author_name(self, author: Element) -> str:
        person = author.find(_TEI + "persName")
        if person is None:
            return ""
        surname = person.find(_TEI + "surname")
        first = person.find(f'{_TEI}forename[@type="first"]')
        middle = person.find(f'{_TEI}forename[@type="middle"]')
        surname_text = self._normalized_text(surname) if surname is not None else ""
        first_text = self._normalized_text(first) if first is not None else ""
        if len(first_text) == 1:
            first_text += "."
        middle_text = self._normalized_text(middle) if middle is not None else ""
        if not surname_text and not first_text and not middle_text:
            return ""
        value = f"{surname_text}, {first_text}"
        if middle_text:
            value += f" {middle_text}"
        return self._clean_value(value)

    @staticmethod
    def _first_title(container: Element | None) -> str:
        if container is None:
            return ""
        title = container.find(_TEI + "title")
        return TEIDocument._normalized_text(title) if title is not None else ""

    @staticmethod
    def _monograph_title(monograph: Element | None) -> str:
        if monograph is None:
            return ""
        title = monograph.find(_TEI + "title")
        return TEIDocument._normalized_text(title) if title is not None else ""

    def _citation_count(self, tei_id: str) -> int:
        target = f"#{tei_id}"
        return sum(
            1
            for citation in self._root.iter(f"{_TEI}ref")
            if citation.get("target") == target
        )

    @staticmethod
    def _normalized_text(node: Element | None) -> str:
        if node is None:
            return ""
        return " ".join(" ".join(node.itertext()).split())

    @staticmethod
    def _clean_value(value: str) -> str:
        return (
            value.replace("\n", " ")
            .replace("\r", "")
            .replace("•", "")
            .replace("+", "")
            .replace("Dipl.", "")
            .replace("Prof.", "")
            .replace("Dr.", "")
            .replace("&apos", "'")
            .replace("❚", "")
            .replace("~", "")
            .replace("®", "")
            .replace("|", "")
            .replace("}", "")
            .replace("{", "")
            .rstrip("\\")
            .strip()
        )
