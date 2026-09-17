import pytest
from defusedxml.ElementTree import fromstring

from app.importing.metadata import ExportMetadata, initial_sidecars, valid_isbn
from app.importing.naming import NamingMetadata


def test_export_preserves_unicode_and_escapes_untrusted_metadata():
    value = ExportMetadata(
        medium="audio",
        naming=NamingMetadata(
            title='海 & Harbor <title> "one"',
            authors=["A & B", "A & B"],
            narrators=["Reader <One>"],
            series="Series & Stories",
            sequence="1.5",
            recording_year=2024,
            original_year=1999,
            publisher="Example <Press>",
            isbn="978-0-306-40615-7",
            asin="B012345678",
            language="en",
        ),
        description="A <script>fictional description</script> & text",
        genres=["Fantasy"],
    )
    files = initial_sidecars(value)
    assert list(files) == ["metadata.opf"]
    assert files == initial_sidecars(value)
    xml = fromstring(files["metadata.opf"])
    dc = "{http://purl.org/dc/elements/1.1/}"
    assert xml.find(f".//{dc}title").text == value.naming.title
    assert [node.text for node in xml.findall(f".//{dc}creator")] == ["A & B", "Reader <One>"]
    assert xml.find(f".//{dc}date").text == "2024"
    assert not xml.findall(".//script")


def test_export_omits_unknown_dates_fake_identifiers_and_unsupported_version_fields():
    value = ExportMetadata(
        medium="ebook",
        naming=NamingMetadata(
            title="A book",
            original_year=1999,
            recording_year=2024,
            source_posted_year=2026,
            narrators=["Not an ebook narrator"],
            isbn="9780306406158",
            asin="internal-version-id",
            edition="Revised",
            abridged=True,
        ),
    )
    text = initial_sidecars(value)["metadata.opf"]
    assert all(
        word not in text
        for word in ("1999", "2024", "2026", "identifier", "nrt", "Revised", "abridged")
    )


@pytest.mark.parametrize("value", ["Bad\x00title", "Bad\ud800title", "Bad\ufffftitle"])
def test_invalid_xml_characters_are_held(value):
    with pytest.raises(ValueError, match="XML-incompatible|unicode"):
        ExportMetadata(medium="ebook", naming=NamingMetadata(title=value))


@pytest.mark.parametrize(
    "value,expected",
    [
        ("0-306-40615-2", "0306406152"),
        ("0-8044-2957-X", "080442957X"),
        ("9780306406157", "9780306406157"),
        ("1234567890", None),
    ],
)
def test_export_only_accepts_valid_isbn_checksum(value, expected):
    assert valid_isbn(value) == expected
