"""Generate the source for the checked-in TypeScript API contract."""

import json
from pathlib import Path

from app.main import create_app

root = Path(__file__).resolve().parents[1]
(root / "docs/openapi.json").write_text(json.dumps(create_app().openapi(), indent=2) + "\n")
