import pytest

from app.adapters.catalog_types import BookData, EditionData, SearchPage
from app.domain.hardcover_matching import MatchEvidence, compatible, lookup


def book(**values):
    return BookData(
        provider="hardcover",
        external_id="42",
        title="The Giver of Stars",
        authors=["Jojo Moyes"],
        **values,
    )


@pytest.mark.parametrize(
    "title,authors,expected",
    [
        ("The Giver of Stars (Unabridged)", ["Jojo Moyes"], True),
        ("The Giver of Stars: A Novel", ["Jojo Moyes"], True),
        ("The Giver of Stars", ["Someone Else"], False),
        ("The Giver of Stars (1 of 3)", ["Jojo Moyes"], False),
        ("The Giver of Stars [Dramatized Adaptation]", ["Jojo Moyes"], False),
        ("The Giver of Stars 2", ["Jojo Moyes"], False),
    ],
)
def test_normalization_does_not_erase_identity(title, authors, expected):
    assert compatible(MatchEvidence(title=title, authors=authors), book()) is expected


@pytest.mark.parametrize("suffix", ["A Study Guide", "Dramatized Adaptation", "The Graphic Novel"])
def test_provider_derivative_is_not_matched_to_original(suffix):
    evidence = MatchEvidence(title="The Giver of Stars", authors=["Jojo Moyes"])
    candidate = book().model_copy(update={"title": f"The Giver of Stars: {suffix}"})
    assert not compatible(evidence, candidate)


def test_stacked_labels_preserve_narrator_credit():
    from app.domain.catalog_titles import display_title, title_narrators

    title = "The Giver of Stars (read by Julia Whelan) (Unabridged): A Novel"
    assert display_title(title) == "the giver of stars"
    assert title_narrators(title) == ["Julia Whelan"]


async def test_isbn_match_uses_equivalent_identifier_and_canonical_record():
    evidence = MatchEvidence(
        title="The Giver of Stars (Unabridged)",
        authors=["Jojo Moyes"],
        identifiers=[("isbn", "9780306406157")],
    )
    edition = EditionData(external_id="7", identifiers={"isbn_10": "0306406152"})
    candidate = book(editions=[edition], canonical_id="43")
    calls = []

    async def call(operation, *args):
        calls.append((operation, args))
        if operation == "identifier_search":
            return (
                SearchPage(provider="hardcover", items=[candidate], page=1, has_more=False),
                False,
                None,
            )
        return book().model_copy(update={"external_id": "43"}), False, None

    result = await lookup(evidence, call)
    assert result.status == "matched" and result.basis == "identifier"
    assert result.book.external_id == "43"
    assert calls[1] == ("fetch", ("43",))


async def test_conflicting_identifiers_do_not_fall_back_to_title():
    evidence = MatchEvidence(
        title="The Giver of Stars",
        authors=["Jojo Moyes"],
        identifiers=[("asin", "B000000001"), ("asin", "B000000002")],
    )
    candidates = [
        book(
            editions=[EditionData(external_id=str(i), identifiers={"asin": f"B00000000{i}"})]
        ).model_copy(update={"external_id": str(i)})
        for i in (1, 2)
    ]

    async def call(operation, *args):
        assert operation != "search"
        if operation == "identifier_search":
            return (
                SearchPage(provider="hardcover", items=candidates, page=1, has_more=False),
                False,
                None,
            )
        return next(b for b in candidates if b.external_id == args[0]), False, None

    assert (await lookup(evidence, call)).status == "unmatched"


async def test_canonical_cycle_is_not_accepted():
    candidate = book(canonical_id="43")

    async def call(operation, *args):
        if operation == "search":
            return (
                SearchPage(provider="hardcover", items=[candidate], page=1, has_more=False),
                False,
                None,
            )
        return (
            candidate.model_copy(update={"external_id": "43", "canonical_id": "42"})
            if args[0] == "43"
            else candidate,
            False,
            None,
        )

    assert (
        await lookup(MatchEvidence(title=candidate.title, authors=candidate.authors), call)
    ).status == "unmatched"


async def test_malformed_search_falls_back_to_bounded_title_query():
    from app.adapters.contracts import AdapterError, FailureKind

    candidate = book()
    calls = []

    async def call(operation, *args):
        calls.append(operation)
        if operation == "search":
            raise AdapterError(FailureKind.PARSER, "Malformed unrelated search hit")
        if operation == "title_search":
            return (
                SearchPage(provider="hardcover", items=[candidate], page=1, has_more=False),
                False,
                None,
            )
        return candidate, False, None

    result = await lookup(MatchEvidence(title=candidate.title, authors=candidate.authors), call)
    assert result.status == "matched"
    assert calls == ["search", "title_search", "fetch"]


async def test_bbc_dramatisation_does_not_make_original_novel_ambiguous():
    original = BookData(
        provider="hardcover", external_id="384057", title="'Salem's Lot", authors=["Stephen King"]
    )
    adaptation = original.model_copy(
        update={
            "external_id": "2318197",
            "title": (
                "Salem's Lot: The BBC full-cast dramatisation plus Secret Window, Secret Garden"
            ),
        }
    )

    async def call(operation, *args):
        if operation == "search":
            return (
                SearchPage(
                    provider="hardcover", items=[original, adaptation], page=1, has_more=False
                ),
                False,
                None,
            )
        assert args[0] == original.external_id
        return original, False, None

    match = await lookup(MatchEvidence(title=original.title, authors=original.authors), call)
    assert match.status == "matched"
    assert match.book.external_id == original.external_id


async def test_ambiguous_results_include_books_to_review():
    first = book()
    second = book().model_copy(update={"external_id": "43"})

    async def call(operation, *args):
        if operation == "search":
            return (
                SearchPage(provider="hardcover", items=[first, second], page=1, has_more=False),
                False,
                None,
            )
        return first if args[0] == "42" else second, False, None

    match = await lookup(MatchEvidence(title=first.title, authors=first.authors), call)
    assert match.status == "unmatched"
    assert [b.external_id for b in match.candidates] == ["42", "43"]


def test_missing_subtitle_separator_preserves_full_title_identity():
    candidate = BookData(
        provider="hardcover",
        external_id="1831181",
        title="Empire of AI: Dreams and Nightmares in Sam Altman's OpenAI",
        authors=["Karen Hao"],
    )
    assert compatible(
        MatchEvidence(
            title="Empire of AI Dreams and Nightmares in Sam Altman's OpenAI", authors=["Karen Hao"]
        ),
        candidate,
    )
    assert not compatible(
        MatchEvidence(title="Empire of AI Other Stories", authors=["Karen Hao"]), candidate
    )


@pytest.mark.parametrize(
    "suffix,expected",
    [
        (" (Cat and Mouse, #2)", True),
        (" (Cat and Mouse #2)", True),
        (" (Cat and Mouse, #2.5)", True),
        (" (Cat and Mouse, #1-2)", False),
        (" (Cat and Mouse, #1–#2)", False),
        (" (Cat and Mouse)", False),
        (" (Graphic Novel, #2)", False),
    ],
)
def test_goodreads_series_membership_is_not_the_title(suffix, expected):
    candidate = BookData(
        provider="hardcover",
        external_id="565267",
        title="Hunting Adeline",
        authors=["H. D. Carlton"],
    )
    evidence = MatchEvidence(title="Hunting Adeline" + suffix, authors=["H.D. Carlton"])
    assert compatible(evidence, candidate) is expected
    assert not compatible(evidence, candidate.model_copy(update={"title": "Haunting Adeline"}))
    assert not compatible(evidence, candidate.model_copy(update={"authors": ["Other Writer"]}))


async def test_hunting_adeline_saved_book_resolves_full_canonical_details():
    evidence = MatchEvidence(title="Hunting Adeline (Cat and Mouse, #2)", authors=["H.D. Carlton"])
    candidate = BookData(
        provider="hardcover",
        external_id="565267",
        title="Hunting Adeline",
        authors=["H. D. Carlton"],
    )
    calls = []

    async def call(operation, *args):
        calls.append((operation, args))
        if operation == "search":
            assert args[0] == "hunting adeline H.D. Carlton"
            return (
                SearchPage(provider="hardcover", items=[candidate], page=1, has_more=False),
                False,
                None,
            )
        assert operation == "fetch" and args == ("565267",)
        return candidate, False, None

    result = await lookup(evidence, call)
    assert result.status == "matched"
    assert result.book.external_id == "565267"
    assert len(calls) == 2


def test_conflicting_explicit_series_numbers_stay_distinct():
    evidence = MatchEvidence(title="Same Title (Series, #1)", authors=["Writer"])
    candidate = BookData(
        provider="hardcover", external_id="1", title="Same Title (Series, #2)", authors=["Writer"]
    )
    assert not compatible(evidence, candidate)
