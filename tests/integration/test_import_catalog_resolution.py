# ruff: noqa: F811
import pytest

from app.adapters.contracts import AdapterError, FailureKind
from app.importing import catalog_resolution as resolution
from app.importing.match_evidence import IdentifierEvidence, MatchEvidence
from tests.catalog_resolution_fixture import resolution_provider  # noqa: F401

pytestmark = pytest.mark.integration


def inputs():
    return {
        "title": "First Harbor",
        "authors": ["Alex Morgan"],
        "requester_id": "reader",
        "account_generation": 7,
        "sources": [],
        "settings": {"primary": "hardcover"},
    }


def facts(medium="ebook"):
    return MatchEvidence(
        titles=["first harbor"],
        authors=[["alex morgan"]],
        languages=["en"],
        narrators=[["jordan lee"]] if medium == "audio" else [],
        identifiers=[IdentifierEvidence(namespace="isbn", value="9781234567897")],
    )


@pytest.mark.parametrize(
    "provider,medium", [("hardcover", "ebook"), ("hardcover", "audio"), ("openlibrary", "ebook")]
)
async def test_provider_resolution_loads_editions_and_preserves_account_routing(
    database, resolution_provider, provider, medium
):
    resolution_provider["medium"] = medium
    book, status, _ = await resolution.provider_lookup(
        provider, inputs(), facts(medium), medium, "requester-token"
    )
    assert status == "completed" and book
    assert len(book.editions) == (51 if provider == "hardcover" else 1)
    assert len(resolution.matching_editions(book, facts(medium), medium)) == 1
    assert not book.editions_more
    assert all(
        auth == ("Bearer requester-token" if provider == "hardcover" else None)
        for _, auth in resolution_provider["calls"]
    )


@pytest.mark.parametrize(
    "fault", ["title", "truncated", "ambiguous", "narrator", "limit", "overlap"]
)
async def test_incomplete_or_conflicting_catalogs_never_resolve(
    database, resolution_provider, fault
):
    resolution_provider["medium"] = "audio"
    resolution_provider["fault"] = fault
    if fault == "limit":
        resolution_provider["pages"] = 11
    book, status, _ = await resolution.provider_lookup(
        "hardcover", inputs(), facts("audio"), "audio", "requester-token"
    )
    assert not book
    assert status == ("completed" if fault == "narrator" else "needs-review")


@pytest.mark.parametrize(
    "fault,kind", [("quota", FailureKind.RATE_LIMIT), ("stale", FailureKind.UNAVAILABLE)]
)
async def test_unavailable_catalog_does_not_assert_a_fresh_edition(
    database, resolution_provider, fault, kind
):
    resolution_provider["fault"] = fault
    with pytest.raises(AdapterError) as caught:
        await resolution.provider_lookup("hardcover", inputs(), facts(), "ebook", "requester-token")
    assert caught.value.kind == kind
    assert "private-provider-response" not in str(caught.value)
    if fault == "quota":
        assert caught.value.retry_after == 3600


async def test_public_fallback_never_borrows_another_users_token(database, resolution_provider):
    book, _, _ = await resolution.lookup(inputs(), facts(), "ebook", None)
    assert book.provider == "openlibrary"
    assert all(auth is None for _, auth in resolution_provider["calls"])
    resolution_provider["calls"].clear()
    book, status, _ = await resolution.lookup(inputs(), facts("audio"), "audio", None)
    assert not book and status == "needs-review" and not resolution_provider["calls"]


async def test_rejected_source_is_not_reattached(database, resolution_provider):
    context = inputs()
    context["sources"] = [{"provider": "hardcover", "external_id": "42", "accepted": False}]
    book, status, message = await resolution.provider_lookup(
        "hardcover", context, facts(), "ebook", "requester-token"
    )
    assert not book and status == "needs-review" and "rejected" in message
    assert len(resolution_provider["calls"]) == 1
