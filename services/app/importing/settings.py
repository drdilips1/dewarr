from app.db.models import OrganizationSettings
from app.importing.naming import NamingProfile


async def current_profile(db):
    row = await db.get(OrganizationSettings, 1, populate_existing=True)
    return NamingProfile.model_validate(row.profile if row else {})
