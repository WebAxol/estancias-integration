# Estancias Integration

Monorepo that runs the backend services together with Docker Compose.

| Folder | Repository | Role |
| ------ | ---------- | ---- |
| `api/` | [estancias-api](https://github.com/WebAxol/estancias-api) (submodule) | FastAPI service |
| `db/`  | [estancias-db](https://github.com/WebAxol/estancias-db) (submodule) | PostgreSQL migrations |

Prometheus and Grafana are planned and not part of the stack yet.

## Requirements

- Git
- Docker
- Docker Compose v2

## Run it

1. Clone with submodules (or fetch them in an existing clone):

   ```bash
   git clone --recurse-submodules <integration-repo-url>
   # existing clone:
   git submodule update --init
   ```

2. Create your env file and fill in the blank values (`POSTGRES_PASSWORD`, `JWT_SECRET`, `BOOTSTRAP_ADMIN_PASSWORD`):

   ```bash
   cp .env.sample .env
   ```

3. Build and start the stack:

   ```bash
   docker compose up -d --build
   docker compose ps
   ```

4. Check the API. It listens on `127.0.0.1:${API_PORT}` (default 8000):

   ```bash
   curl http://127.0.0.1:8000/docs
   ```

Postgres is available on `127.0.0.1:${POSTGRES_PORT}` (default 5432). Both ports are bound to localhost only.

## Common commands

```bash
docker compose logs -f api          # follow API logs
docker compose exec db psql -U estancias_user -d estancias
docker compose down                 # stop, keep data
docker compose down -v              # stop and delete the db_data volume
```

SQL files in `db/migrations/` run only when the `db_data` volume is created. After changing a migration, run `docker compose down -v` and start again. This deletes all data.

## Configuration

All variables live in the root `.env` (ignored by git). `.env.sample` lists them.

| Variable | Used by | Description |
| -------- | ------- | ----------- |
| `TZ` | db, api | Container time zone |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | db, api | Database name and credentials |
| `POSTGRES_PORT` | db | Host port for Postgres |
| `API_PORT` | api | Host port for the API |
| `JWT_SECRET`, `JWT_TTL_MINUTES` | api | Token signing key and lifetime |
| `DB_POOL_MAX_SIZE` | api | Max database connections |
| `BOOTSTRAP_ADMIN_*`, `BOOTSTRAP_SUBSIDIARY_ID` | api | First admin created at startup |

The API reaches Postgres at host `db`, port `5432`. Compose sets this itself, so `.env` has no `POSTGRES_HOST`.

## Updating submodules

Pull the latest commit of each submodule and record it in this repo:

```bash
git submodule update --remote
git add api db
git commit -m "Update submodules"
```

To work on a service, `cd` into its folder, commit and push there first, then commit the new pointer here.
