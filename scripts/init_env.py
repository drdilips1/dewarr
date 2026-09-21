"""Create installation secrets without printing or replacing them."""

import argparse
import base64
import os
import secrets
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--mode", choices=["native", "compose"], default="compose")
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
create_secret("bootstrap_token", secrets.token_urlsafe(40))
password = create_secret("postgres_password", secrets.token_urlsafe(32))
prefix = "/run/secrets/" if args.mode == "compose" else str(secret_dir) + "/"
db = (
    f"postgresql+psycopg://book:{password}@postgres:5432/book"
    if args.mode == "compose"
    else "postgresql+psycopg://book@127.0.0.1:55438/book_search_dev"
)
with env.open("x") as file:
    os.chmod(env, 0o600)
    file.write(
        f"BOOK_DATABASE_URL={db}\nBOOK_PUBLIC_URL=http://localhost:8000\n"
        f"BOOK_SECRET_KEY_FILE={prefix}app_key\nBOOK_BOOTSTRAP_TOKEN_FILE={prefix}bootstrap_token\n"
        f"BOOK_COOKIE_SECURE=false\nBOOK_UID={os.getuid()}\nBOOK_GID={os.getgid()}\n"
    )
print(f"Created .env for {args.mode}. Setup token: .local/secrets/bootstrap_token")
print("Keep .local/secrets/app_key with your database backups. No secrets were printed.")
