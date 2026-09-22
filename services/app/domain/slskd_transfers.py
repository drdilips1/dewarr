"""Queue one Soulseek folder on the connected slskd downloader."""

from app.adapters.contracts import AdapterError, FailureKind
from app.adapters.slskd import SlskdClient
from app.db.session import session_factory
from app.domain.slskd_connection import integration
from app.security import decrypt_secrets

OFFLINE = "Connect and test Soulseek before downloading this folder"


async def _credentials():
    async with session_factory()() as db:
        row = await integration(db)
        if not row or not row.enabled:
            return None
        api_key = decrypt_secrets(row.encrypted_secrets).get("api_key")
        if not api_key:
            return None
        return row.base_url, api_key, row.status


async def queue_folder(release, attempt_id: str) -> None:
    found = await _credentials()
    if not found or found[2] != "connected":
        raise AdapterError(FailureKind.UNSUPPORTED, OFFLINE)
    endpoint, api_key, _status = found
    async with SlskdClient(endpoint, api_key) as client:
        await client.enqueue(release, attempt_id=attempt_id)


async def cancel_folder(username: str, attempt_id: str) -> None:
    found = await _credentials()
    if not found:
        return
    endpoint, api_key, _status = found
    try:
        async with SlskdClient(endpoint, api_key) as client:
            await client.cancel(username, attempt_id)
    except AdapterError:
        return
