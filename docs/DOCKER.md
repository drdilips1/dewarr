# Docker setup

## Standard installation

The root `compose.yaml` pulls `ghcr.io/logabell/dewarr:latest`. It runs the web/API server, background worker, PostgreSQL, and database migrations. API and worker must use the same image.

```sh
git clone https://github.com/logabell/dewarr.git
cd dewarr
python3 scripts/init_env.py --mode compose
docker compose up -d
docker compose ps
```

Open http://localhost:8000. Create your first administrator account on the welcome page. No setup token or default login is needed. Once an account exists, public registration closes.

The setup script creates random credentials and refuses to overwrite an existing `.env`. It uses Python's standard library. Keep `.env` and `.local/secrets` private.

## Build from source

```sh
docker compose -f compose.yaml -f deploy/compose.build.yaml up -d --build
```

Use the same `-f` arguments for future updates, logs, and stop commands. Building requires no local Python packages or Node.js: both build stages run inside Docker.

## Image versions

`latest` follows the main branch. Tagged releases use tags such as `v0.1.0`; commit builds have `sha-` tags. Pin a published tag or digest in `.env` to control upgrades:

```dotenv
DEWARR_IMAGE=ghcr.io/logabell/dewarr:v0.1.0
```

Container publishing runs in [GitHub Actions](../.github/workflows/container.yml) for Linux amd64 and arm64. If a new image is still building, use the source-build setup above.

## LAN or reverse proxy

The default port binds to loopback. To access the app from your LAN, edit `.env`:

```dotenv
DEWARR_BIND=0.0.0.0
DEWARR_PORT=8000
BOOK_PUBLIC_URL=http://your-server:8000
BOOK_COOKIE_SECURE=false
```

`BOOK_PUBLIC_URL` must exactly match the browser origin, without a path. Apply changes with `docker compose up -d`.

For HTTPS, point your reverse proxy to port 8000, set the public URL to `https://books.example.com`, and set `BOOK_COOKIE_SECURE=true`. Forward the original Host header. If the proxy is another container on this Compose network, its upstream is `http://api:8000`; loopback refers to the proxy container itself.

## Shared media folders

API and worker both need access to download and library paths. This example mounts one common parent so hardlinks can work when the filesystem supports them.

```sh
mkdir -p data/downloads data/audiobooks data/staging
docker compose -f compose.yaml -f deploy/compose.media.yaml up -d
```

Set `BOOK_UID` and `BOOK_GID` in `.env` to the user/group that owns these folders. The setup script uses your current IDs. On Linux, files and secret mounts must be readable by that container user; media folders must be writable. Containers run without root privileges.

In **Settings → Libraries**, connect Audiobookshelf and choose `/data/audiobooks` as the path Dewarr sees. If Audiobookshelf sees `/audiobooks`, map that to `/data/audiobooks` in Dewarr. Configure staging under `/data/staging`. In downloader settings, map qBittorrent's completed-download path to `/data/downloads`.

For environment-managed routes, the equivalent optional `.env` values are:

```dotenv
BOOK_IMPORT_SOURCES={"downloads":"/data/downloads"}
BOOK_IMPORT_DESTINATIONS={"audiobooks":"/data/audiobooks"}
BOOK_IMPORT_STAGING_ROOT=/data/staging
```

The path keys identify roots; configure and verify the matching routes in the UI. Mounts alone do not enable importing. Do not point staging at a library folder.

## Add Audiobookshelf

For a new Audiobookshelf instance alongside Dewarr:

```sh
mkdir -p data/downloads data/audiobooks data/staging
docker compose -f compose.yaml -f deploy/compose.media.yaml -f deploy/compose.audiobookshelf.yaml up -d
```

Open http://localhost:13378 and set up Audiobookshelf. Add its library at `/audiobooks`. In Dewarr, connect to `http://audiobookshelf:80` and use an Audiobookshelf API token. Dewarr sees the same files at `/data/audiobooks`.

Already have Audiobookshelf? Connect its reachable URL instead. Do not use `localhost` for a different container. On Docker Desktop, `host.docker.internal` reaches a service on the host. On Linux, use a reachable host address or a shared Docker network.

## Existing qBittorrent

Connect qBittorrent's Web UI URL and credentials in **Settings → Downloaders**. Give it access to the same download directory. A downloader path such as `/downloads` needs a mapping to Dewarr's `/data/downloads`.

Dewarr does not need qBittorrent to browse books or sync lists. Configure sources, verify a destination, and choose download policies first. To allow dispatch, set:

```dotenv
BOOK_DOWNLOAD_DISPATCH_ENABLED=true
```

Recreate API and worker with `docker compose up -d`, then enable the desired list or request automation in the UI. Connecting a reading account does not enable automatic downloading.

## Docker run with an existing PostgreSQL server

Compose is the easiest option. For an existing PostgreSQL installation, create a database/user, generate secrets with the setup script, and change `BOOK_DATABASE_URL` in `.env` to a database address reachable from containers. The database user must be able to create tables and the worker's queue schema.

```sh
docker network create dewarr
docker run --rm --network dewarr --user "$(id -u):$(id -g)" --env-file .env \
  --mount type=bind,src="$PWD/.local/secrets",dst=/run/secrets,readonly \
  ghcr.io/logabell/dewarr:latest alembic upgrade head

docker run -d --name dewarr-api --network dewarr --restart unless-stopped \
  --user "$(id -u):$(id -g)" --env-file .env \
  --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
  -p 127.0.0.1:8000:8000 \
  --mount type=bind,src="$PWD/.local/secrets",dst=/run/secrets,readonly \
  ghcr.io/logabell/dewarr:latest

docker run -d --name dewarr-worker --network dewarr --restart unless-stopped \
  --user "$(id -u):$(id -g)" --env-file .env \
  --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
  --mount type=bind,src="$PWD/.local/secrets",dst=/run/secrets,readonly \
  ghcr.io/logabell/dewarr:latest python -m app.jobs.worker
```

Add `--mount type=bind,src="$PWD/data",dst=/data` to both API and worker when importing media. Container `.env` values are literal: use plain JSON for path settings, without surrounding shell quotes.

## Backups

Stop writers, dump PostgreSQL, and copy the encryption key and configuration to a private backup location:

```sh
mkdir -p backups
chmod 700 backups
docker compose stop api worker
docker compose exec -T postgres pg_dump -U book -d book -Fc > backups/dewarr.dump
cp -R .local/secrets backups/secrets
cp .env backups/install.env
docker compose start api worker
```

Also back up library media. A database dump cannot decrypt saved integration credentials without the original app key. Protect backups like passwords. For application-aware backup/restore and paused recovery review, see [Recovery](RECOVERY.md); do not directly activate an old worker queue after restoring a dump.

## Updates and troubleshooting

```sh
docker compose pull
docker compose stop api worker
docker compose up -d
docker compose ps
docker compose logs --tail=100 api worker migrate
```

- **Setup cannot connect:** check PostgreSQL health and migration logs.
- **Sign-in/origin error:** match `BOOK_PUBLIC_URL` to the URL in your browser.
- **Lists stop refreshing:** keep the worker running and check the reading-account connection.
- **Permission denied:** verify container UID/GID, secret readability, and shared-folder permissions.
- **Downloads do not start:** check dispatch, policies, source connection, capacity, and verified routes.
- **Registry denies a pull:** confirm the container workflow has finished and the package is public; use a local build in the meantime.

`docker compose down` stops the stack and keeps its named database volume. `docker compose down -v` deletes that volume.
