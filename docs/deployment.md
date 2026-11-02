# Deployment

StudySmart's Docker Compose setup is a **reproducible local environment with production-style serving**: Nginx in front of Gunicorn with `DEBUG` off, over plain HTTP on the loopback interface. This document covers how it is put together, how a clean installation and data persistence were verified, the security review, and what a production or cloud deployment would need. Setup steps for a new developer are in the [README quick start](../README.md#quick-start).

## Docker Compose environment

| Service | Image | Host port | Data |
| --- | --- | --- | --- |
| `nginx` | `nginx:1.30.6-alpine` with [nginx/default.conf](../nginx/default.conf) | `127.0.0.1:8000` | Named volume `studysmart_static_data`, read-only |
| `web` | Built from the [Dockerfile](../Dockerfile): Python 3.12 slim with GDAL, GEOS and PROJ; `collectstatic`, then Gunicorn with 3 workers; unprivileged `django` user | none (port 8000 inside the network) | Source code bind-mounted at `/app`; `studysmart_static_data` at `/app/staticfiles` |
| `db` | `postgis/postgis:17-3.6` | none | Named volume `studysmart_postgres_data` |
| `pgadmin` | `dpage/pgadmin4:9.18.0` | `127.0.0.1:5050` | Named volume `studysmart_pgadmin_data` |

- **Network:** a dedicated bridge network, `studysmart_network`, with a configurable private subnet (`DOCKER_SUBNET`). Services reach each other by name (`web`, `db`); no container address is hard-coded. Nginx looks up `web` through Docker's DNS on each request, so recreating `web` does not leave it with an old address.
- **Start order:** `db` has a `pg_isready` health check; `web` and `pgadmin` start only once it is healthy; `nginx` starts after `web`. Migrations are run explicitly, not on every start.
- **Static files:** `web` runs `collectstatic` on each start, copying the app, admin and API files into the `static_data` volume. Nginx serves them from there with a 7-day cache lifetime. File names have no content hash, so a longer lifetime or `immutable` could leave visitors with stale JavaScript.
- **Code changes:** Gunicorn does not reload code. After changing Python, JavaScript or CSS, run `docker compose restart web`.
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

This gives the test its own containers, network and volumes. The same approach can be used to try any branch without touching an existing database. That installation predates Nginx: today the site's port would be overridden on the `nginx` service, as `web` no longer publishes one.

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

### Nginx and Gunicorn verification

On **2026-11-02** the stack was rebuilt from empty volumes in the development checkout (`docker compose down -v`, `docker compose up -d --build`) with `DJANGO_DEBUG=False`, then migrated and imported.

| Check through `http://localhost:8000` | Result |
| --- | --- |
| Imports | 5 areas, 24 libraries and 633 cafés created |
| `/`, `/about/`, `/api/`, `/api/spaces/nearby/?lat=53.34371&lng=-6.25443&radius=1000` | 200 (250 spaces nearby) |
| `/static/spaces/js/map.js`, the font, and the admin, GeoDjango and DRF static files | 200 with correct content types; 7-day cache headers |
| Response headers on pages, static files and 404s | `Server: nginx` with no version; `X-Frame-Options`, `X-Content-Type-Options` and `Referrer-Policy` each sent once |
| `Host: evil.example` | 400 |
| `web` has no host port; recreating `web` | No published port; Nginx reached the new container without a restart |
| Admin login in a headless browser and with `curl`, including the CSRF `Origin` check | Logged in; pages styled; map widget showed OpenStreetMap tiles |
| API create and delete with a session and CSRF token; anonymous create | 201 and 204; 403 |
| `check --deploy` | Only `security.W004`, `W008`, `W012` and `W016`, which need HTTPS |

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
| Network | The database and Gunicorn have no host port; Nginx and pgAdmin listen on `127.0.0.1` only; the web container runs as an unprivileged user |
| Nginx | The only entry point to the site. Hides its version (`server_tokens off`), limits request bodies to 5 MB, and mounts only the static files (read-only), so it cannot read the source code or `.env`. Passes `Host`, `X-Forwarded-For` and `X-Forwarded-Proto` to Django, which still checks `Host` against the allowed hosts |
| Browser | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, or `strict-origin-when-cross-origin` on `/admin/` so that the map widget's OpenStreetMap tiles are not blocked (set by Nginx on every response, replacing Django's copies so that each is sent once), `Cross-Origin-Opener-Policy: same-origin` (from Django); API text inserted with `textContent`; CDN files pinned with Subresource Integrity hashes |

These are covered by tests (see [testing.md](testing.md)). `manage.py check --deploy` with `DJANGO_DEBUG=False` (2026-11-02) reports:

| Warning | Meaning | Status |
| --- | --- | --- |
| `security.W004`, `W008`, `W012`, `W016` | No HSTS, no HTTPS redirect, session and CSRF cookies not secure-only | These settings require HTTPS, which the local `http://localhost` setup does not have. `DJANGO_HTTPS=True` enables them all |

No other warnings are reported. A local `.env` with `DJANGO_DEBUG=True` adds `security.W018`. With `DJANGO_DEBUG=False` and `DJANGO_HTTPS=True`, `check --deploy` reports **no issues** (tested). HSTS preload (`security.W021`) is deliberately silenced: it adds the domain to a list built into browsers, which is hard to undo, so the domain owner should opt in.

## Production and cloud deployment

The local setup already serves the site through Nginx and Gunicorn, but it is deliberately not production-ready. Deploying StudySmart publicly, for example on a cloud virtual machine or container service with a managed PostgreSQL that supports PostGIS (such as Azure Database for PostgreSQL, Amazon RDS or Google Cloud SQL), would need these steps:

1. **Database:** create a managed PostgreSQL 16+ instance, enable the `postgis` extension, and create a **restricted application role** that owns only the StudySmart schema (not a superuser). Enable automated backups.
2. **Application server:** keep Gunicorn behind Nginx, and remove the source bind mount so that the container runs the code in its image.
3. **Static files:** keep serving the collected files with Nginx, or move them to a CDN. Add content-hashed file names (`ManifestStaticFilesStorage`) before making the cache lifetime longer than a week.
4. **HTTPS and Django settings:** add a TLS certificate to Nginx, publish it on port 443, and set `DJANGO_ALLOWED_HOSTS` to the public domain and `DJANGO_HTTPS=True`. That one setting turns on the HTTPS redirect, HSTS, secure-only cookies, `CSRF_TRUSTED_ORIGINS` for the allowed hosts and `SECURE_PROXY_SSL_HEADER`, which reads the `X-Forwarded-Proto` header that Nginx sets. If a load balancer ends TLS in front of Nginx instead, Nginx must pass on the load balancer's header rather than its own `$scheme`, or the redirect would loop.
5. **Secrets:** store them in the platform's secret manager instead of a `.env` file.
6. **Release process:** build the image in CI, run `migrate` as a one-off release step, run the imports once, and promote the image only when CI is green.
7. **Operations:** do not expose pgAdmin publicly; add logging and monitoring, and consider rate limiting and pagination for the public API.
8. **Map tiles:** OpenStreetMap's public tile servers are not intended for heavy production traffic; use a commercial or self-hosted tile service at scale.

(This document was made with assistance from OpenAI Codex)