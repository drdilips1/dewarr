"""Create installation secrets without printing or replacing them."""

import argparse
import base64
import os
import secrets
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--mode", choices=["native"], default="native")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
env = root / ".env"
if env.exists():
    raise SystemExit(".env already exists; leaving it and the installation secrets unchanged")
secret_dir = root / ".local/secrets"
secret_dir.mkdir(parents=True, exist_ok=True, mode=0o700)


def create_secret(name, value):
    path = secret_dir / name
    if path.exists():
        return path.read_text().strip()
    with path.open("x") as file:
        os.chmod(path, 0o600)
        file.write(value + "\n")
    return value


create_secret("app_key", base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
password = create_secret("postgres_password", secrets.token_urlsafe(32))
prefix = str(secret_dir) + "/"
db = "postgresql+psycopg://book@127.0.0.1:55438/book_search_dev"
with env.open("x") as file:
    os.chmod(env, 0o600)
    file.write(
        f"BOOK_DATABASE_URL={db}\nBOOK_PUBLIC_URL=http://localhost:8000\n"
        f"BOOK_SECRET_KEY_FILE={prefix}app_key\n"
        "BOOK_COOKIE_SECURE=false\n"
    )
print(f"Created .env for {args.mode}. Open Dewarr to create your first administrator account.")
print("Keep .local/secrets/app_key with your database backups. No secrets were printed.")
