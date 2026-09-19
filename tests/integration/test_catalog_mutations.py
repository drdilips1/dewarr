from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app.adapters.contracts import FailureKind, MutationError
from app.db.models import ProviderBudget, ProviderCache
from app.domain.catalog_network import CatalogGateway

pytestmark = pytest.mark.integration


async def test_mutations_never_read_populate_or_fall_back_to_metadata_cache(database):
    calls = []
    failed = False

    def respond(request):
        calls.append(request)
        return httpx.Response(503 if failed else 200, json={"data": {"receipt": len(calls)}})

    async with CatalogGateway(
        "hardcover", "account:1", "mutation-test-token", transport=httpx.MockTransport(respond)
    ) as gateway:
        # Even a matching legacy cache key cannot impersonate a mutation response.
        await gateway.request(
            "POST", "v1/graphql", json={"query": "mutation Example { change }", "variables": {}}
        )
        first = await gateway.mutate("mutation Example { change }", {})
        second = await gateway.mutate("mutation Example { change }", {})
        assert first["data"]["receipt"] == 2 and second["data"]["receipt"] == 3
        failed = True
        with pytest.raises(MutationError) as caught:
            await gateway.mutate("mutation Example { change }", {})
        assert caught.value.may_have_applied and len(calls) == 4 and not gateway.stale
        async with database() as db:
            assert await db.scalar(select(func.count()).select_from(ProviderCache)) == 1


@pytest.mark.parametrize(
    "status,uncertain", [(401, False), (403, False), (429, False), (503, True), (200, True)]
)
async def test_http_failure_classification_retains_ambiguous_effects(database, status, uncertain):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            status, content="not-json", headers={"Retry-After": "60"} if status == 429 else {}
        )

    async with CatalogGateway(
        "hardcover", "account:1", "mutation-test-token", transport=httpx.MockTransport(respond)
    ) as gateway:
        with pytest.raises(MutationError) as caught:
            await gateway.mutate("mutation Example { change }", {})
        assert caught.value.may_have_applied is uncertain and len(calls) == 1
        if status == 429:
            assert caught.value.retry_after >= 60
            with pytest.raises(MutationError) as blocked:
                await gateway.mutate("mutation Example { change }", {})
            assert not blocked.value.may_have_applied and len(calls) == 1


async def test_existing_account_cooldown_prevents_mutation_without_network(database):
    def unexpected(request):
        pytest.fail("A cooling-down account must not be contacted")

    async with CatalogGateway(
        "hardcover", "account:1", "mutation-test-token", transport=httpx.MockTransport(unexpected)
    ) as gateway:
        async with database() as db, db.begin():
            db.add(
                ProviderBudget(
                    key=gateway.budget_key,
                    next_request_at=datetime.now(UTC),
                    blocked_until=datetime.now(UTC) + timedelta(minutes=5),
                )
            )
        with pytest.raises(MutationError) as caught:
            await gateway.mutate("mutation Example { change }", {})
        assert caught.value.kind == FailureKind.RATE_LIMIT and not caught.value.may_have_applied
