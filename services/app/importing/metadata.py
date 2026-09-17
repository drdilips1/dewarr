"""Deterministic initial sidecars; never rewrite media or existing ABS metadata."""

import re
from xml.etree import ElementTree as ET

from pydantic import Field, model_validator

from app.importing.naming import NamingMetadata, StrictModel


class ExportMetadata(StrictModel):
    medium: str = Field(pattern=r"^(ebook|audio)$")
    naming: NamingMetadata
    description: str | None = Field(default=None, max_length=60000)
    genres: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def valid_xml_values(self):
        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, list):
                for member in value:
                    yield from strings(member)
            elif isinstance(value, dict):
                for member in value.values():
                    yield from strings(member)

        for value in strings(self.model_dump()):
            if any(
                not (
                    character in "\t\n\r"
                    or 0x20 <= ord(character) <= 0xD7FF
                    or 0xE000 <= ord(character) <= 0xFFFD
                    or 0x10000 <= ord(character) <= 0x10FFFF
                )
                for character in value
            ):
                raise ValueError("Export metadata contains an XML-incompatible character")
        if not self.naming.title.strip():
            raise ValueError("An initial metadata export needs a resolved title")
        return self


def valid_isbn(value):
    if not value:
        return None
    cleaned = re.sub(r"[\s-]", "", value).upper()
    if re.fullmatch(r"\d{9}[\dX]", cleaned):
        digits = [int(character) if character != "X" else 10 for character in cleaned]
        if sum((10 - index) * digit for index, digit in enumerate(digits)) % 11 == 0:
            return cleaned
    if re.fullmatch(r"97[89]\d{10}", cleaned):
        if (
            sum(int(digit) * (1 if index % 2 == 0 else 3) for index, digit in enumerate(cleaned))
            % 10
            == 0
        ):
            return cleaned
    return None


def initial_sidecars(metadata: ExportMetadata) -> dict[str, str]:
    facts = metadata.naming
    package = ET.Element("package", {"xmlns": "http://www.idpf.org/2007/opf", "version": "2.0"})
    container = ET.SubElement(
        package,
        "metadata",
        {
            "xmlns:dc": "http://purl.org/dc/elements/1.1/",
            "xmlns:opf": "http://www.idpf.org/2007/opf",
        },
    )

    def add(name, value, **attributes):
        if value is not None and str(value).strip():
            ET.SubElement(container, name, attributes).text = str(value).strip()

    add("dc:title", facts.title)
    add("dc:subtitle", facts.subtitle)
    for author in dict.fromkeys(name.strip() for name in facts.authors if name.strip()):
        add("dc:creator", author, **{"opf:role": "aut"})
    if metadata.medium == "audio":
        for narrator in dict.fromkeys(name.strip() for name in facts.narrators if name.strip()):
            add("dc:creator", narrator, **{"opf:role": "nrt"})
    add("dc:language", facts.language)
    year = facts.recording_year if metadata.medium == "audio" else facts.edition_year
    if year:
        add("dc:date", f"{year:04}")
    add("dc:publisher", facts.publisher)
    add("dc:description", metadata.description)
    for genre in dict.fromkeys(value.strip() for value in metadata.genres if value.strip()):
        add("dc:subject", genre)
    if isbn := valid_isbn(facts.isbn):
        add("dc:identifier", isbn, **{"opf:scheme": "ISBN"})
    if facts.asin and re.fullmatch(r"[A-Z0-9]{10}", facts.asin):
        add("dc:identifier", facts.asin, **{"opf:scheme": "ASIN"})
    if facts.series and facts.series.strip():
        ET.SubElement(
            container, "meta", {"name": "calibre:series", "content": facts.series.strip()}
        )
        if facts.sequence and facts.sequence.strip():
            ET.SubElement(
                container,
                "meta",
                {"name": "calibre:series_index", "content": facts.sequence.strip()},
            )
    # Edition labels, abridgment and app IDs have no certified OPF import contract
    # in ABS. Keep them in our version/manifest, never invent an ISBN or ASIN.
    return {"metadata.opf": ET.tostring(package, encoding="utf-8", xml_declaration=True).decode()}
