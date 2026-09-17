"""Inventory installed frontend packages and retain their supplied notices."""

import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
web = root / "apps/web"
lock = json.loads((web / "package-lock.json").read_text())
inventory = []
notices = []
for relative, entry in sorted(lock["packages"].items()):
    if not relative or not (web / relative / "package.json").exists():
        continue  # Optional packages for other platforms are not installed/bundled here.
    package = web / relative
    metadata = json.loads((package / "package.json").read_text())
    inventory.append(
        {
            "name": metadata["name"],
            "version": metadata["version"],
            "license": metadata.get("license", "UNDECLARED"),
            "development": bool(entry.get("dev")),
        }
    )
    included = []
    for file in sorted(package.iterdir()):
        if file.is_file() and file.name.lower().startswith(
            ("license", "licence", "copying", "notice")
        ):
            included.append(file.read_text(errors="replace"))
    notices.append(
        f"{metadata['name']} {metadata['version']}\n"
        f"Declared license: {metadata.get('license', 'UNDECLARED')}\n\n" + "\n\n".join(included)
    )
(root / "docs/frontend-dependencies.json").write_text(json.dumps(inventory, indent=2) + "\n")
(root / "docs/notices/frontend-third-party.txt").write_text("\n\n".join(notices) + "\n")
print(f"Recorded {len(inventory)} installed frontend packages and their supplied notices.")
