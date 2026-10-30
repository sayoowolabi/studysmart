# Deployment

StudySmart's Docker Compose setup is a **reproducible local development environment**. This document covers how it is put together, how a clean installation and data persistence were verified, the security review, and what a production or cloud deployment would need. Setup steps for a new developer are in the [README quick start](../README.md#quick-start).

## Docker Compose environment

| Service | Image | Host port | Data |
| --- | --- | --- | --- |
| `web` | Built from the [Dockerfile](../Dockerfile): Python 3.12 slim with GDAL, GEOS and PROJ; Django's development server; unprivileged `django` user | `127.0.0.1:8000` | Source code bind-mounted at `/app` |
| `db` | `postgis/postgis:17-3.6` | none | Named volume `studysmart_postgres_data` |
| `pgadmin` | `dpage/pgadmin4:9.18.0` | `127.0.0.1:5050` | Named volume `studysmart_pgadmin_data` |

- **Network:** a dedicated bridge network, `studysmart_network`, with a configurable private subnet (`DOCKER_SUBNET`). Services reach each other by name (`db`); no container address is hard-coded.
- **Start order:** `db` has a `pg_isready` health check; `web` and `pgadmin` start only once it is healthy. Migrations are run explicitly, not on every start.
- **Configuration:** Compose passes only the variables each service needs from `.env`; `docker compose config` fails with a clear message if a required one is missing. Django refuses to start with a missing or placeholder secret.
- **Data:** the source snapshots are part of the repository (`data/raw/`) and reach the container through the bind mount; they are excluded from the image.

## Clean installation verification

On **2026-10-30** the application was installed from a fresh clone of `main` (commit `4efc69c`), following only the README, while the existing development stack kept running.

To keep the test separate, the clone's `.env` was created from `.env.example` with new secrets plus `COMPOSE_PROJECT_NAME=studysmart-final` and `DOCKER_SUBNET=172.30.70.0/24`. An uncommitted `docker-compose.override.yml` in the clone published it on other host ports:

```yaml
services:
  web:
    ports: !override
      - "127.0.0.1:28000:8000"
  pgadmin:
    ports: !override
      - "127.0.0.1:25050:80"
```

This gives the test its own containers, network and volumes. The same approach can be used to try any branch without touching an existing database.

| Step | Result |
| --- | --- |
| `docker compose config --quiet`, `build web` | Passed |
| `up -d db pgadmin`, `run --rm web … migrate`, `up -d web` | Database healthy; all migrations applied |
| `import_administrative_areas --repair-invalid` (dry run, then real), `import_libraries`, `import_cafes` | 5 areas, 24 libraries and 633 cafés created (408 OSM cafés outside the area and 49 unnamed ones reported and skipped) |
| The three imports again | Everything `unchanged`; no duplicates |
| `check --database default`, `pip check` | No issues; no broken requirements |
| `test spaces --shuffle` | 129 tests passed |
| Browser tests against port 28000 | 39 of 39 passed |
| HTTP checks of every route | Page, API root, list, detail, filters, nearby, nearest, areas and coverage 200; invalid filter and radius 400; unknown ID and no nearest match 404; anonymous writes 403; write to coverage 405; admin redirects to login; pgAdmin login page 200 |

Nothing needed from outside the repository was found: code, migrations, data snapshots, checksums and identity maps are all in Git. The first build needs internet access for the base images and Python packages.

## Data persistence

PostgreSQL data lives in the named volume `studysmart_postgres_data`, which survives stopping, restarting and recreating containers. Only `docker compose down -v` (or removing the volume) deletes it.

Verified on **2026-10-30** with `docker compose restart` on the development stack. Before and after: 657 study spaces, 5 areas, 19 migration records with their original timestamps, 1 user, and an identical checksum of every study space's ID, name, location and facilities. The volume was the original one created on 2026-10-27. Persistence across `docker compose down` / `up -d` (container recreation) was verified in Issue #1.

To repeat the check:

```powershell
docker compose exec web /usr/local/bin/python manage.py shell -c "from spaces.models import StudySpace as S; print(S.objects.count())"
docker compose restart          # or: docker compose down; docker compose up -d   (never add -v)
docker compose exec web /usr/local/bin/python manage.py shell -c "from spaces.models import StudySpace as S; print(S.objects.count())"
docker compose exec web /usr/local/bin/python manage.py showmigrations spaces
```

Named volumes are not backups. A backup can be taken with `docker compose exec db pg_dump -U <user> -Fc <database> > studysmart.dump`.

## Security review

| Area | Implementation |
| --- | --- |
| Secrets | Only in environment variables from `.env`, which is ignored by Git and Docker and has never been committed. Django stops if `DJANGO_SECRET_KEY` or a database setting is missing or still a `change-me` placeholder |
| Debug and hosts | `DEBUG` defaults to off and accepts only `True`/`False`. Allowed hosts default to `localhost`, `127.0.0.1` and `[::1]`; other `Host` headers get 400 |
| Authentication | Django sessions with CSRF protection; HTTP Basic disabled; writes need the matching model permission |
| API | Only the study-space list and detail accept writes; searches and area endpoints are read-only. Inputs are validated by serializers and the model's `full_clean()`; provenance fields are read-only |
| Network | The database has no host port; Django and pgAdmin listen on `127.0.0.1` only; the web container runs as an unprivileged user |
| Browser | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `Cross-Origin-Opener-Policy: same-origin`; API text inserted with `textContent`; CDN files pinned with Subresource Integrity hashes |

These are covered by tests (see [testing.md](testing.md)). `manage.py check --deploy` (2026-10-30) reports:

| Warning | Meaning | Status |
| --- | --- | --- |
| `security.W018` | `DEBUG` is on | From the local `.env` only; disappears with `DJANGO_DEBUG=False` |
| `security.W004`, `W008`, `W012`, `W016` | No HSTS, no HTTPS redirect, session and CSRF cookies not secure-only | These settings require HTTPS, which the local `http://localhost` setup does not have. They must be enabled in production |

No other warnings are reported.

## Production and cloud deployment

The local setup is deliberately not production-ready. Deploying StudySmart publicly, for example on a cloud virtual machine or container service with a managed PostgreSQL that supports PostGIS (such as Azure Database for PostgreSQL, Amazon RDS or Google Cloud SQL), would need these steps:

1. **Database:** create a managed PostgreSQL 16+ instance, enable the `postgis` extension, and create a **restricted application role** that owns only the StudySmart schema (not a superuser). Enable automated backups.
2. **Application server:** replace `runserver` with a WSGI server such as Gunicorn (one new dependency) behind the platform's HTTPS load balancer or Nginx.
3. **Static files:** set `STATIC_ROOT`, run `collectstatic` during the build, and serve the files with Nginx, a CDN or WhiteNoise.
4. **HTTPS and Django settings:** `DJANGO_DEBUG=False`; set `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` to the public domain; enable `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` and `SECURE_HSTS_SECONDS`, which clears the four `check --deploy` warnings. Behind a proxy, also set `SECURE_PROXY_SSL_HEADER`.
5. **Secrets:** store them in the platform's secret manager instead of a `.env` file.
6. **Release process:** build the image in CI, run `migrate` as a one-off release step, run the imports once, and promote the image only when CI is green.
7. **Operations:** do not expose pgAdmin publicly; add logging and monitoring, and consider rate limiting and pagination for the public API.
8. **Map tiles:** OpenStreetMap's public tile servers are not intended for heavy production traffic; use a commercial or self-hosted tile service at scale.
