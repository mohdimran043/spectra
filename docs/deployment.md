# SPECTRA deployment

How SPECTRA is built, packaged and run — on a developer laptop, and on an
operator's LAN or air-gapped host.

---

## 1. The model in one page

SPECTRA ships to operators as a **sealed bundle**. Developers produce artifacts;
operators run one script. No registry, no compiler and no Git access on the
target host.

Two invariants make that work.

### Two compose files, never merged

| File | Audience | Contains |
|------|----------|----------|
| `deploy/docker-compose.yml` | developers | `build:` contexts, named volumes, dev-friendly defaults |
| `deploy/docker-compose.lan.yml` | operators | images only, pinned to `${APP_VERSION}`, all state bind-mounted under `$APP_ROOT` |

The LAN compose has **no `build:`, no `version:` key and no `:latest` tag**, and
hardcodes no hostname, port, password or path. The identical file ships to every
site as the bundle's `docker-compose.yml`. The only per-site inputs are `.env`,
the TLS material in `$APP_ROOT/certs`, and the config templates installed into
`$APP_ROOT/config` on the first deploy.

### Two artifacts

| Artifact | Name | Contains | When |
|----------|------|----------|------|
| **Full release** | `spectra-<VERSION>-release.tar.gz` | every image (app + third-party), compose, SQL, scripts, config, UI | greenfield install, or any version change |
| **Patch bundle** | `spectra-<VERSION>-YYYYMMDD-pN.tar.gz` | only the changed service images, optionally migrations and UI | a host already running the same base `VERSION` |

`VERSION` at the repository root is the single source of truth for image tags,
bundle names and `APP_VERSION`. `latest` is never used anywhere.

---

## 2. Repository layout of this layer

```
VERSION                          1.0.0 - the source of truth
CHANGELOG.md                     one section per release
Makefile                         developer convenience (NOT shipped in bundles)
.dockerignore                    build-context filter for the Python images

Each Dockerfile lives with the thing it builds:

services/api/Dockerfile          multi-stage; `--target worker` also builds the worker
services/worker/Dockerfile       layers on a built api image
apps/frontend/Dockerfile         Next.js standalone, non-root `node`
apps/mock-enterprise/Dockerfile  same shape, port 3001

The two Python images build from the repository root, because they install the
whole monorepo. The two Next.js apps build from their own directory, so their
context is a few hundred kilobytes instead of the entire tree, and each carries
its own `.dockerignore`.

deploy/
├── docker-compose.yml           DEV stack (builds)
├── docker-compose.gpu.yml       DEV GPU overlay
├── docker-compose.lan.yml       OPERATOR stack (images only)
├── docker-compose.lan.gpu.yml   OPERATOR GPU overlay
├── .env.example                 every site value, CHANGE_ME for every secret
├── config/                      templates copied to $APP_ROOT/config once
└── scripts/                     the operator script set + lib/common.sh

db/
├── baseline/001_control_plane.sql      greenfield control-plane schema
├── baseline/002_enterprise_demo.sql    enterprise schema + read-only role
└── migrations/0001_init.sql            ordered, append-only stream

scripts/
├── package-release.sh           cut a full bundle
├── package-patch.sh             cut a patch bundle
├── bootstrap.sh gpu-check.sh model-health.sh lint.sh test.sh
```

---

## 3. Developer workflow

### First time

```bash
make install                 # ./scripts/bootstrap.sh - venv + deps, no Docker
cp deploy/.env.example deploy/.env   # then replace the CHANGE_ME values
make up                      # full stack in Docker (add GPU=1 for NVIDIA)
make db-migrate              # baseline + migrations
make seed-demo               # demo corpus and demo database rows
make verify                  # probe the API and every datastore
```

`deploy/.env` is the compose project's env file: Compose reads it automatically
for the dev stack, and `make db-migrate`, `make verify` and `make state` pass it
to the operator scripts. Without it the dev stack still starts on the defaults
baked into `deploy/docker-compose.yml`, but those three targets will tell you
the file is missing. `deploy/.env` is git-ignored — it holds credentials.

The stack comes up at:

| Service | URL |
|---------|-----|
| Analyst frontend | <http://localhost:3000> |
| Mock enterprise app | <http://localhost:3001> |
| API | <http://localhost:8000/api/health> |

Datastore ports bind to `127.0.0.1` only.

### Cutting a release

```
- [ ] 1. make version-bump V=patch|minor|major
- [ ] 2. add a CHANGELOG.md entry for the new version
- [ ] 3. make sync-deploy-env
- [ ] 4. make lint && make test
- [ ] 5. make audit               # the offline-bundle invariants
- [ ] 6. commit
- [ ] 7. make package-release
- [ ] 8. validate the bundle on a clean VM (no prior images, empty APP_ROOT)
- [ ] 9. transfer the tarball AND its .sha256 to the operator
```

### Cutting a patch

Use a patch only when the target host already runs the same base `VERSION` and
only a subset of services changed. Patches never carry third-party images.

```bash
make package-patch SVC='api worker'      # two services
make package-patch SVC=api DB=1          # api plus new migrations
make package-patch UI=1                  # UI only (implies frontend + mock-enterprise)
make package-patch SVC=api DB=1 UI=1
```

The patch id is `<BASE_VERSION>-YYYYMMDD-pN`. **`pN` is computed, never chosen.**
The packager scans `releases/`, `releases/patches/` and
`releases/patches/applied/` for the highest sequence already used for that base
version and day, then adds one. Patch images are tagged with the patch id, not
the base version: `spectra-api:1.0.0-20260917-p1`.

---

## 4. GPU: why an overlay rather than a compose profile

The api and worker want optional NVIDIA access; datastores must never request
it. The obvious reach is `COMPOSE_PROFILES=gpu`, and it does not work here:

* A Compose profile adds or removes a **whole service**. It cannot add a
  `deploy.resources.reservations.devices` block to an existing one.
* Expressing GPU access as a profile therefore needs a second, profile-gated
  copy of `api`. The unprofiled copy always starts, so both run and collide on
  `container_name` — and the duplicate drifts from the original on every edit.
* A single file with `count: 0` is not a reliable "no GPU" signal either; the
  request still reaches the nvidia hook.

So the reservation lives in a small overlay that changes only the four lines
that differ:

```bash
# developer
make up GPU=1
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.gpu.yml up -d

# operator: set GPU_ENABLED=1 in .env and deploy.sh adds the overlay itself
docker compose -f docker-compose.yml -f docker-compose.lan.gpu.yml up -d
```

Without the overlay the stack starts unchanged on a GPU-less machine. On such a
host set `MODEL_PROFILE=cpu`; the gateway reports degraded mode rather than
failing. `./scripts/gpu-check.sh` reports driver, CUDA, container-runtime and
PyTorch state, and names the specific blocker — a driver/library version
mismatch, or a missing container runtime — explicitly.

**On the current host the overlay is not yet usable.** The RTX 4090 itself works
(driver 580.178.04, `torch 2.8.0+cu128`), but the NVIDIA Container Toolkit is not
installed, so `docker info` lists only `runc` and `gpu-check` warns accordingly.
Keep `GPU_ENABLED=0` — with `GPU_ENABLED=1`, `verify-deployment.sh` fails the GPU
check and `up` fails with `could not select device driver "nvidia" with
capabilities: [[gpu]]`. Install the toolkit, run
`sudo nvidia-ctk runtime configure --runtime=docker`, restart Docker, and the
overlay works as designed.

---

## 5. Operator workflow

### First install

```bash
tar -xzf spectra-1.0.0-release.tar.gz
cd spectra-1.0.0
sha256sum -c CHECKSUMS.sha256          # optional but recommended

cp .env.example .env
$EDITOR .env
#   * replace EVERY CHANGE_ME (10 of them)
#   * set APP_ROOT (default /opt/spectra) and SPECTRA_PUBLIC_HOST
#   * passwords must be URL-safe: no @ : / ? # %

./scripts/deploy.sh
./scripts/verify-deployment.sh
```

`deploy.sh` runs nine steps: preflight → state tree → config → TLS → images →
database (start, wait, back up when upgrading, migrate) → UI → `up -d` →
record state. It refuses to start while any `CHANGE_ME` remains, and also
refuses if the *rendered* compose config still contains one.

### Upgrade

```bash
cp /path/to/previous-bundle/.env .env    # carries every site-specific value
./scripts/deploy.sh                      # backs up automatically before migrating
./scripts/verify-deployment.sh
```

An upgrade is detected from `$APP_ROOT/.deployed_version`, not from whether
`.env` exists. `deploy.sh` also clears any `SERVICE_*_IMAGE` pins left behind by
patches — otherwise the new release would quietly keep running one old service.
Use `--keep-image-overrides` if holding a patch is deliberate.

### Applying a patch

Patches run against the **live deploy directory**, not a fresh extract.

```bash
# once per host, only if it predates patch support:
./scripts/bootstrap-patch-support.sh

cp spectra-1.0.0-20260917-p1.tar.gz ./releases/patches/
./scripts/deploy-patch.sh
```

`deploy-patch.sh` verifies checksums, refuses a base-version mismatch, loads the
images, writes the `SERVICE_*_IMAGE` pins into `.env`, runs migrations when the
patch carries them, stages the UI, recreates **only** the patched services with
`--no-deps --force-recreate`, records the event and moves the archive into
`releases/patches/applied/`.

### Rollback

```bash
./scripts/rollback.sh /path/to/spectra-0.9.0/
```

**Rollback reverts images and the UI only. The database schema is never rolled
back automatically.** Migrations are forward-only. If the release being undone
ran a destructive migration, restore the pre-upgrade dump *before* starting the
old images:

```bash
ls $APP_ROOT/backups/
gunzip -c $APP_ROOT/backups/<dir>/spectra.sql.gz \
  | docker compose exec -T postgres psql -U spectra -d spectra
```

Restoring a dump discards everything written since it was taken. That decision
belongs to the operator; no script makes it automatically.

---

## 6. `$APP_ROOT` layout

Everything persistent lives under `$APP_ROOT` (default `/opt/spectra`). The
bundle itself stays read-only; only `.env` is edited in place.

```
$APP_ROOT/
├── config/                       operator-editable config, installed once and never overwritten
│   └── spectra-overrides.env     optional env_file for api and worker
├── certs/                        server.crt, server.key
├── data/
│   ├── app/                      SPECTRA runtime data (uploads, processed, objects)
│   ├── postgres/  qdrant/  opensearch/  neo4j/{data,logs}/  redis/  minio/
├── models/                       model weights (override with SPECTRA_MODEL_DIR)
├── releases/
│   ├── ui/<version|patch-id>/    staged UI builds; `current` points at the live one
│   └── patches/                  patch inbox; applied/ once used
├── backups/                      timestamped pg_dump snapshots + manifest.txt
├── .deployed_version             plain text, one line
├── .deployed-state.json          per-service images, last action, recent history
└── .deployed-history.jsonl       append-only deployment journal
```

`.deployed-state.json` is regenerated from the journal on every deploy, so the
scripts never need a JSON parser — there is no `jq` on a sealed host.

**A deliberate deviation from the generic pattern:** SPECTRA's UI is served by
the `frontend` container (Next.js standalone), not by nginx from a bind mount.
`releases/ui/` is therefore a provenance and rollback record of which UI build
is live, not a web root. UI patches work by replacing the frontend image; the
staged copy exists so you can see and prove what is running.

---

## 7. Databases

Two databases in one PostgreSQL instance:

| Database | Purpose | Written by |
|----------|---------|-----------|
| `spectra` | control plane: sources, assets, chunks, entities, entity_keys, entity_links, ingest_jobs, index_versions | the API and worker |
| `spectra_enterprise` | the `enterprise` demo business schema: customers, transactions, incidents, assets | nobody at runtime |

The split is deliberate: "query a real business database" must be a genuine
external-source path for the Database Agent, not a privileged internal
shortcut. The agent and the mock enterprise application both connect as
`spectra_readonly`, which holds `SELECT` on the `enterprise` schema and nothing
else, plus `default_transaction_read_only = on` and a role-level
`statement_timeout`. `verify-deployment.sh` proves both halves: that the role can
read, and that an `INSERT` as that role is refused.

| Directory | When it runs | Rule |
|-----------|--------------|------|
| `db/baseline/` | once, on an empty database | never edit to change a live deployment |
| `db/migrations/` | every deploy, and any patch with `DB=1` | append-only, ordered, idempotent |

`run-migrations.sh` records every applied file with its SHA-256 in
`spectra_schema_history` and **stops** if a recorded file changed on disk. Each
file declares its target with `-- spectra:target=control|enterprise`. See
`db/migrations/README.md` for the full convention.

---

## 8. Every Make target as a direct command

Make is a convenience. Nothing in SPECTRA requires it, and release bundles ship
no Makefile at all.

| Make target | Direct command |
|-------------|----------------|
| `make help` | `grep -E '^[a-zA-Z_-]+:.*?## ' Makefile` |
| `make install` | `./scripts/bootstrap.sh` |
| `make install-ml` | `./scripts/bootstrap.sh --ml` |
| `make install-backends` | `./scripts/bootstrap.sh --backends` |
| `make up` | `export APP_VERSION=$(cat VERSION); docker compose -f deploy/docker-compose.yml up -d --build` |
| `make up GPU=1` | `export APP_VERSION=$(cat VERSION); docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.gpu.yml up -d --build` |
| `make start` | same as `make up` |
| `make down` | `docker compose -f deploy/docker-compose.yml down` |
| `make restart` | `docker compose -f deploy/docker-compose.yml up -d --force-recreate --no-deps api worker frontend mock-enterprise` |
| `make logs` | `docker compose -f deploy/docker-compose.yml logs -f --tail 200` |
| `make logs S=api` | `docker compose -f deploy/docker-compose.yml logs -f --tail 200 api` |
| `make ps` | `docker compose -f deploy/docker-compose.yml ps` |
| `make db-migrate` | `SPECTRA_COMPOSE_FILE=$PWD/deploy/docker-compose.yml SPECTRA_ENV_FILE=$PWD/deploy/.env ./deploy/scripts/run-migrations.sh` |
| `make verify` | `SPECTRA_COMPOSE_FILE=$PWD/deploy/docker-compose.yml SPECTRA_ENV_FILE=$PWD/deploy/.env ./deploy/scripts/verify-deployment.sh` |
| `make state` | `SPECTRA_COMPOSE_FILE=$PWD/deploy/docker-compose.yml SPECTRA_ENV_FILE=$PWD/deploy/.env ./deploy/scripts/show-state.sh` |
| `make seed-demo` | `.venv/bin/spectra seed-demo` |
| `make ingest SRC=./demo-data` | `.venv/bin/spectra ingest ./demo-data` |
| `make reindex` | `.venv/bin/spectra reindex` |
| `make demo` | `.venv/bin/spectra demo` |
| `make test` | `./scripts/test.sh` |
| `make lint` | `./scripts/lint.sh` |
| `make format` | `./scripts/lint.sh --fix` |
| `make benchmark` | `.venv/bin/python -m spectra_eval` |
| `make gpu-check` | `./scripts/gpu-check.sh` |
| `make model-health` | `./scripts/model-health.sh` |
| `make version-bump V=patch` | edit `VERSION` by hand, then `make sync-deploy-env` |
| `make sync-deploy-env` | `sed -i -E "s/^APP_VERSION=.*/APP_VERSION=$(cat VERSION)/" deploy/.env deploy/.env.example` |
| `make package-release` | `./scripts/package-release.sh` |
| `make package-patch SVC='api worker' DB=1 UI=1` | `SVC='api worker' DB=1 UI=1 ./scripts/package-patch.sh` |
| `make compose-validate` | `docker compose -f deploy/docker-compose.yml config -q` and `APP_VERSION=$(cat VERSION) APP_ROOT=/tmp/x docker compose -f deploy/docker-compose.lan.yml config -q` |
| `make audit` | the seven-line audit in §10 |

Operator-side commands are always the scripts themselves — `./scripts/deploy.sh`
and friends. If you ever see `make <target>` in operator documentation, that is
a bug.

---

## 9. Troubleshooting

### `ERROR: APP_VERSION is required`

`docker compose` was run without `APP_VERSION` in the environment. The LAN
compose deliberately fails loudly rather than starting untagged images.

```bash
export APP_VERSION=$(cat VERSION)          # in the repo
export APP_VERSION=$(grep ^APP_VERSION .env | cut -d= -f2)   # on a host
# or simply use the scripts, which export it for you
```

`APP_ROOT` fails the same way, for the same reason.

### `COMPOSE_PROJECT_NAME` mismatch

`deploy.sh` stops with *"a SPECTRA stack is already running under compose project
'X'"*. Compose addresses containers, networks and volumes by project name;
renaming mid-life orphans all of them. Find what the running stack actually uses
and adopt it:

```bash
docker inspect spectra-api --format '{{ index .Config.Labels "com.docker.compose.project" }}'
# then either set COMPOSE_PROJECT_NAME=<that> in .env, or:
./scripts/bootstrap-patch-support.sh
```

### `deploy-patch.sh` cannot find a bundle

The archive is in the wrong folder. With no argument the script looks in exactly
two inboxes, newest first:

```
<deploy-dir>/releases/patches/
$APP_ROOT/releases/patches/
```

Copy it into either and rerun with no arguments, or pass the path explicitly:
`./scripts/deploy-patch.sh /media/usb/spectra-1.0.0-20260917-p2.tar.gz`.

### Patch id collision

`package-patch.sh` refuses because the computed bundle directory already exists,
or `deploy-patch.sh` refuses because that archive is already in `applied/`.
Deleting a patch archive after building it does **not** free its sequence — the
scanner also reads `applied/`, precisely so ids are never reused. Build the next
sequence. If you must re-apply an identical patch, `--force` is available and
records the repeat in the journal.

### UI missing or stale after a deploy

SPECTRA serves the UI from the `frontend` container, so first check the image
actually running:

```bash
./scripts/show-state.sh            # SERVICE / IMAGE / HEALTH table
docker compose logs frontend --tail 100
```

A stale UI almost always means a leftover `SERVICE_FRONTEND_IMAGE` pin in
`.env` from an old patch. `show-state.sh` prints pins under "Image pins in
.env"; `deploy.sh` clears them on a full release. `$APP_ROOT/releases/ui/current`
tells you which build was staged, but it is a record — it is not what is served.

### Database rollback is manual, always

`rollback.sh` reverts images and UI. It does not revert schema, and no flag
makes it. Restore from `$APP_ROOT/backups/` first if the newer release migrated
destructively, then roll back the images. Write forward-only migrations
(expand, backfill, contract in a much later release) and this situation mostly
stops arising — see `db/migrations/README.md`.

### OpenSearch will not start

```bash
sudo sysctl -w vm.max_map_count=262144
echo 'vm.max_map_count=262144' | sudo tee /etc/sysctl.d/99-spectra.conf
```

`verify-deployment.sh` checks this and warns before OpenSearch fails.

### `could not select device driver "nvidia" with capabilities: [[gpu]]`

`GPU_ENABLED=1` but the NVIDIA Container Toolkit is not registered with Docker.
Either install it (`sudo nvidia-ctk runtime configure --runtime=docker &&
sudo systemctl restart docker`) or set `GPU_ENABLED=0` and `MODEL_PROFILE=cpu`.
`./scripts/gpu-check.sh` says which of the two you are looking at.

### A bind-mounted datastore fails with permission errors

Each image runs as a fixed uid; the host directory must match. `deploy.sh` does
this with `chown_data_dirs`, but silently skips it when not run as root. Fix by
hand using the uids in `.env` (`QDRANT_UID`, `OPENSEARCH_UID`, `NEO4J_UID`,
`REDIS_UID`, `MINIO_UID`, `APP_UID`):

```bash
sudo chown -R 1000:1000 $APP_ROOT/data/opensearch
```

PostgreSQL is the documented exception: its entrypoint starts as root, fixes
`PGDATA` itself and drops privileges before serving.

---

## 10. The two-minute audit

Run this before packaging anything. Every failure is a blocker for an offline
bundle.

```bash
test -f VERSION && echo "VERSION: OK"
! grep -q 'build:' deploy/docker-compose.lan.yml && echo "LAN compose has no build: OK"
! grep -qE 'image:.*:latest' deploy/docker-compose.lan.yml && echo "no latest tags: OK"
! grep -q '^version:' deploy/docker-compose.lan.yml && echo "no version key: OK"
test -d db/baseline && test -d db/migrations && echo "db split: OK"
test -x scripts/package-release.sh && test -x deploy/scripts/deploy.sh && echo "scripts executable: OK"
grep -c CHANGE_ME deploy/.env.example

docker compose -f deploy/docker-compose.yml config -q
APP_VERSION=$(cat VERSION) APP_ROOT=/tmp/spectra-root \
  docker compose -f deploy/docker-compose.lan.yml config -q
```

`make audit` and `make compose-validate` run the same checks.

### Before adding a service

- [ ] added to **both** compose files, with the LAN one tagged `${APP_VERSION}` and overridable via `SERVICE_<SVC>_IMAGE`
- [ ] `healthcheck` plus `depends_on: condition: service_healthy` for its datastores
- [ ] `container_name`, `restart: unless-stopped`, `stop_grace_period`, bounded `logging`, non-root `user:`
- [ ] any new env var added to `deploy/.env.example` with a safe default or a `CHANGE_ME`
- [ ] added to `SPECTRA_APP_SERVICES` or `SPECTRA_INFRA_SERVICES` in `deploy/scripts/lib/common.sh`
- [ ] added to `package-release.sh` (build) and `package-patch.sh` (valid `SVC` value)
- [ ] probed by `verify-deployment.sh`
