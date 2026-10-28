# StudySmart

StudySmart is an individual Advanced Web Mapping / Location-Based Services university project to help students find study spaces in Dublin.

## Current scope

Issue #1 provides a Django project (`studysmart`), an app (`spaces`), a simple page at `/`, and a Docker development environment with PostGIS and pgAdmin4.

Issue #2 adds a shared `StudySpace` model for libraries and cafés, five nullable facility fields, administrative-area multipolygons, repeatable snapshot imports and Django-admin editing. Source metadata, retrieval times, licences and original attributes are preserved. Unknown facilities remain SQL NULL.

Issue #3 adds a study-space CRUD REST API at `/api/spaces/` with public read access, model-permission-controlled writes and type/facility filters.

Issue #4 adds PostGIS-backed nearby and nearest searches and per-area library/café counts.

Map controls and Leaflet features remain for later issues. The home page is still an initial development page, not a study-space search interface.

## Architecture

```mermaid
flowchart LR
    Browser[Browser: localhost:8000] --> Web[Django / GeoDjango]
    Web --> DB[(PostgreSQL 17 / PostGIS 3.6)]
    Admin[pgAdmin: localhost:5050] --> DB
    DB --> Volume[Named PostgreSQL volume]
```

All three services share a dedicated bridge network with an explicit private subnet. Docker DNS resolves the database as `db`; container addresses are not hard-coded. Only the Django and pgAdmin ports are published, both on the host loopback interface. PostgreSQL has no host port.

Dependencies are Django 5.2 LTS (which includes GeoDjango), Django REST Framework and Psycopg 3. Python 3.12 and GEOS/GDAL/PROJ run inside the Django container. Compose passes environment variables to Django, so no dotenv package is required. Django's development server is used; this is not a production deployment.

## Prerequisites

- Docker Desktop running **Linux containers**, with its WSL 2 backend recommended on Windows.
- Docker Compose supporting health-based dependencies.
- Internet access for the initial image and package downloads.
- Available host ports 8000 and 5050.
- A private subnet that does not overlap your local, VPN or other Docker networks.

A host Python installation is not required for the commands below. Run them from the repository root in PowerShell or the PyCharm terminal.

## Environment configuration

For a new checkout only:

```powershell
Copy-Item .env.example .env
```

Do not overwrite an existing `.env`. Replace the `change-me` values with unique local secrets before starting. Settings reject missing secrets and the provided placeholders.

| Variable | Purpose |
| --- | --- |
| `DJANGO_SECRET_KEY` | Long random Django signing secret |
| `DJANGO_DEBUG` | Exactly `True` or `False`; defaults to false if absent |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames; local defaults exclude wildcards |
| `POSTGRES_DB` | Database created on first initialisation |
| `POSTGRES_USER` | Local development database account |
| `POSTGRES_PASSWORD` | Unique database password |
| `PGADMIN_DEFAULT_EMAIL` | pgAdmin login email |
| `PGADMIN_DEFAULT_PASSWORD` | Separate pgAdmin password |
| `DOCKER_SUBNET` | Dedicated subnet; defaults to `172.30.50.0/24` |

A PowerShell 5.1-compatible way to generate one random secret is:

```powershell
$generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$secretBytes = New-Object byte[] 48
$generator.GetBytes($secretBytes)
[BitConverter]::ToString($secretBytes).Replace('-', '').ToLowerInvariant()
$generator.Dispose()
```

Repeat for each secret and enter the values locally. Do not share the output. Single-quoted values in `.env` preserve literal `$` and `#` characters.

`.env` is ignored by Git and excluded from Docker's build context. `.env.example` contains placeholders only. Compose explicitly passes only the environment variables each service needs. Django does not load `.env` directly.

## Start the environment

```powershell
docker compose config --quiet
docker compose build web
docker compose up -d db pgadmin
docker compose run --rm web /usr/local/bin/python manage.py migrate
docker compose up -d web
docker compose ps
```

The database health check waits for PostgreSQL to accept TCP connections. Both dependent services wait for that health check. Migrations remain an explicit command, rather than running on every web-server restart.

Open:

- Django: [http://localhost:8000/](http://localhost:8000/)
- Django admin: [http://localhost:8000/admin/](http://localhost:8000/admin/)
- pgAdmin: [http://localhost:5050/](http://localhost:5050/)

The first image build and pgAdmin initialisation can take several minutes. A running container may not yet be serving HTTP; inspect its logs and retry the page once initialisation completes.

Optionally create a Django administrator interactively:

```powershell
docker compose exec web /usr/local/bin/python manage.py createsuperuser
```

Django administrator credentials are separate from pgAdmin and database credentials.

In pgAdmin, log in using your local `PGADMIN_DEFAULT_*` values, then register a server:

| Field | Value |
| --- | --- |
| Name | StudySmart |
| Host name/address | `db` |
| Port | `5432` |
| Maintenance database | Your `POSTGRES_DB` value |
| Username/password | Your `POSTGRES_USER` and `POSTGRES_PASSWORD` values |

Inside pgAdmin's container, `localhost` means pgAdmin itself, not PostgreSQL.

## Checks and tests

```powershell
docker compose exec web /usr/local/bin/python manage.py check --database default
docker compose exec web /usr/local/bin/python -m pip check
docker compose exec web /usr/local/bin/python manage.py showmigrations
docker compose exec web /usr/local/bin/python manage.py test spaces
(Invoke-WebRequest -UseBasicParsing http://localhost:8000/).StatusCode
```

Tests cover:

- environment checks
- models and tri-state facility parsing
- seated-café selection
- admin permissions and corrections
- repeat imports and geometry validation/transformation
- the CRUD API (permissions, validation, filters, imported-record protection)
- spatial searches using known geometries

Database tests create a separate test database and remove it afterwards; they do not delete the application database. Import tests use clearly fictional fixtures and make no network calls.

To verify the actual application database through Django:

```powershell
@'
from django.db import connection
with connection.cursor() as cursor:
    cursor.execute("SELECT current_database(), PostGIS_Version()")
    print(cursor.fetchone())
'@ | docker compose exec -T web /usr/local/bin/python manage.py shell
```

The PowerShell here-string avoids nested command-line quoting. You can also enter these statements in an interactive `manage.py shell`.

## Stop, restart and verify persistence

Temporarily stop/start the existing containers:

```powershell
docker compose stop
docker compose start
```

Stop and remove this project's containers and network, retaining the named volumes:

```powershell
docker compose down
docker compose up -d
```

Never add `-v` when retaining database data. PostgreSQL uses `studysmart_postgres_data`; pgAdmin configuration uses `studysmart_pgadmin_data`. Database files are mounted at `/var/lib/postgresql/data` for the selected PostgreSQL 17 image.

To manually verify persistence:

1. Create a Django administrator and confirm login works.
2. Run `docker compose restart`; confirm login still works.
3. Run `docker compose down`, then `docker compose up -d`.
4. Confirm the same login still works and `showmigrations` still lists applied migrations.

Named volumes survive container recreation, but are not backups.

## PyCharm and Docker Desktop

Open the repository in PyCharm and use its terminal for the Compose commands. In editions supporting Docker Compose interpreters, select service `web` and interpreter `/usr/local/bin/python`. Otherwise, keep running management commands in the terminal; installing Windows GDAL libraries is unnecessary.

In Docker Desktop, expand the `studysmart` project to see `web`, `db` and `pgadmin`. Check service logs, database health, published ports and the two named volumes. Use `docker network inspect studysmart_studysmart_network` to verify the configured subnet and membership.

## Troubleshooting and limitations

- **OneDrive:** this checkout is inside OneDrive. Source bind mounts can be slower and reload notifications may be unreliable. If edits are not detected, run `docker compose restart web`. Keep database files in Docker named volumes, not a OneDrive bind mount.
- **Subnet collision:** choose another unused private CIDR in `DOCKER_SUBNET`. If this project's network already exists, recreate its containers/network with `docker compose down` and `docker compose up -d`, retaining volumes.
- **Port collision:** stop the conflicting local service or edit the host-side port mapping. Do not stop unrelated containers without checking.
- **Database credentials:** initialisation variables apply only to an empty database volume. Editing a password in `.env` does not change an existing database role's password.
- **Development permissions:** Django uses the image's bootstrap PostgreSQL account, which is a superuser. Use a separate restricted application role before deploying beyond local development.
- **Secrets:** ignored environment files are local plaintext, not encrypted storage. Docker administrators can inspect container environments. Do not share resolved Compose configuration or commit credentials.
- **Deployment:** local HTTP, optional debug output and `runserver` are for development. Production needs a deployment server, HTTPS, restricted database roles and a security review.
- **Network isolation:** the dedicated bridge separates this stack from unrelated Compose networks; it is not an air gap and permits outbound traffic.
- **Image versions:** database and Python tags are versioned but not digest-locked. Do not change PostgreSQL major versions against an existing data volume without a migration/backup plan.
- **Logs:** use `docker compose logs --tail 50 web db pgadmin` locally, and redact sensitive information before sharing.

## Issue #1 verification

Verified locally with Docker Desktop's Linux engine and Docker Compose:

| Check | Result |
| --- | --- |
| Compose configuration and Django image build | Passed |
| Built-in Django migrations | All 18 applied |
| Django system check with the default database | No issues |
| Python dependency check | No broken requirements |
| Django tests | All 9 passed, including a live PostGIS query |
| Django connection to application database | Connected to `studysmart`; PostGIS 3.6 available |
| HTTP smoke checks | Django home page and pgAdmin login returned 200 |
| Network and volume inspection | Explicit `172.30.50.0/24` bridge; named PostgreSQL volume mounted |
| pgAdmin network connectivity | Resolved `db` and reached TCP port 5432 |
| Persistence after restart and container recreation | All 18 migration records, including timestamps, retained the same checksum; migrations were not rerun |
| Secret handling | `.env` ignored and untracked; absent from the built image |
| Image runtime user | Unprivileged `django` user |

Initial HTTP probes failed while services were still initialising; subsequent probes passed. Interactive pgAdmin server registration and the PyCharm GUI have not been verified automatically. PyCharm's SDK helper could not resolve the project module during verification; all application checks used the explicitly selected interpreter inside Docker.

## Import study-space data (Issue #2)

Read [data sources and import decisions](docs/data-sources.md) for the schema, exact datasets, licences, download instructions, stable identity mappings and known data-quality limitations. The exact source snapshots used for the recorded imports are committed in `data/raw/`, with their checksums, licences and retrieval times in `data/source-manifest.json`. A fresh clone can therefore reproduce the same import without downloading anything. Git stores these files byte-for-byte (`.gitattributes`), so their checksums match on every platform.

To import:

```powershell
docker compose exec web /usr/local/bin/python manage.py migrate
docker compose exec web /usr/local/bin/python manage.py import_administrative_areas --repair-invalid --dry-run
docker compose exec web /usr/local/bin/python manage.py import_administrative_areas --repair-invalid
docker compose exec web /usr/local/bin/python manage.py import_libraries
docker compose exec web /usr/local/bin/python manage.py import_cafes
```

The two invalid source boundaries require the explicit repair flag; repair methods and original validity reasons are recorded. Location imports require the complete area set. Commands accept `--manifest PATH` and `--dry-run`, validate snapshot hashes, report invalid/outside records and never delete missing source records. Reimporting an unchanged snapshot creates no duplicates.

In Django admin, use the category and indoor-seating filters to select cafés with confirmed indoor seats. Unknown-seat cafés remain stored. Editing any facility automatically protects all five facility values from imports and requires evidence notes; source metadata remains read-only. For imported records, name, type, location, address and description are also read-only, matching the API, because the next import would overwrite them. Uncheck the facility lock in a separate save to resume source-owned facility updates.

## Issue #2 verification

Verified locally against PostGIS after applying `spaces.0001_initial`:

| Check | Result |
| --- | --- |
| Django checks and migration consistency | No issues; no unrecorded model changes |
| Automated tests | All 54 passed, including the original 9 environment tests |
| DCC libraries | 24 library/service source records; all five facility attributes unknown |
| OSM cafés | 633 named records inside DCC; 408 outside the study area and 49 unnamed records reported/excluded from the 1,090-element snapshot |
| Café indoor seating | 91 true, 3 false, 539 unknown; the indoor-seat filter selects only the 91 true records |
| Café outdoor seating | 123 true, 90 false, 420 unknown |
| Café Wi-Fi | 29 true, 10 false, 594 unknown |
| Café outlets and laptop permission | Both unknown for all 633 imported cafés |
| Administrative areas | Five valid 2D EPSG:4326 multipolygons; two explicit source repairs recorded |
| Spatial indexes | GiST indexes confirmed for points and boundaries |
| Repeated real imports | Zero creations/updates; all study-space primary keys, source IDs and import timestamps preserved |

These counts describe the recorded snapshots, not live coverage or independently verified venue facilities. The first real boundary import exposed Z ordinates and source self-intersections; handling and tests were updated before the final successful run. A preliminary admin-form test failed because it requested an unlock while expecting protected-field validation; the corrected test and final suite passed.

## Study-space REST API (Issue #3)

| Method | Endpoint | Access | Success |
| --- | --- | --- | --- |
| GET | `/api/spaces/` | Public | 200, JSON list |
| GET | `/api/spaces/{id}/` | Public | 200 |
| POST | `/api/spaces/` | `spaces.add_studyspace` permission | 201 |
| PATCH | `/api/spaces/{id}/` | `spaces.change_studyspace` permission | 200 |
| DELETE | `/api/spaces/{id}/` | `spaces.delete_studyspace` permission | 204 |

PUT is not offered (405); use PATCH. Superusers hold all three permissions. Authentication uses the Django session from logging in at `/admin/`, so writes also need a CSRF token; the browsable API at `/api/spaces/` handles this automatically. HTTP Basic authentication is disabled because this development server uses plain HTTP.

### Fields

Requests and responses use `latitude`/`longitude` in EPSG:4326 degrees; the server stores them as a PostGIS `Point(longitude, latitude)`.

| Field | Write rules |
| --- | --- |
| `name`, `space_type` (`library`/`cafe`), `latitude` (−90..90), `longitude` (−180..180) | Required on create |
| `address`, `description` | Optional text |
| `indoor_seating`, `outdoor_seating`, `has_wifi`, `has_outlets`, `laptop_allowed` | `true`, `false` or `null` (unknown, the default) |
| `facility_verification_notes` | Required whenever a facility value is set or changed |
| `id`, `location_method`, `facility_import_locked`, `facility_verified_at`, `source_*`, `imported_at` | Read-only |

Raw `source_attributes` are not exposed. Source URL, licence and kind remain in every record for attribution.

### Filters (list only)

| Parameter | Values |
| --- | --- |
| `type` | `library`, `cafe` |
| `indoor_seating`, `outdoor_seating`, `has_wifi`, `has_outlets`, `laptop_allowed` | `true`, `false`, `unknown` (case-insensitive) |

Filters combine with AND. `true` matches only confirmed values, so `/api/spaces/?type=cafe&indoor_seating=true` excludes cafés with false or unknown seating. `unknown` matches SQL NULL. Any other value returns 400. Results are not paginated and seating values are source-reported, not live occupancy.

### Data-integrity rules

- Setting or changing any facility through the API behaves like the Django admin: all five facility values are protected from future imports, the verification time is recorded and evidence notes are required.
- For imported records (`source_kind` `official` or `osm`), changes to `name`, `space_type`, location, `address` or `description` return 400, because the next import would overwrite them. Correct these in the source data instead.
- Imported records cannot be deleted (409 Conflict), because the next import would recreate them. Manually created records can be edited and deleted normally. API-created records are always `source_kind=manual`.
- Validation reuses the model's own checks (`full_clean()`), including the finite-coordinate validator, so API, admin and import rules match.

### Status codes and errors

| Code | Meaning |
| --- | --- |
| 400 | Validation error, as `{"field": ["message"]}` |
| 403 | Not logged in, missing model permission or missing CSRF token |
| 404 | No study space with that ID |
| 405 | Unsupported method (PUT) |
| 409 | Attempt to delete an imported record |

### Manual check

```powershell
# Public reads (no login)
Invoke-RestMethod "http://localhost:8000/api/spaces/?type=cafe&indoor_seating=true" | Measure-Object
Invoke-WebRequest -UseBasicParsing "http://localhost:8000/api/spaces/?indoor_seating=maybe"   # 400
Invoke-WebRequest -UseBasicParsing -Method Post "http://localhost:8000/api/spaces/" -ContentType "application/json" -Body '{}'   # 403
```

For writes, log in at `/admin/`, open `/api/spaces/` and use the browsable API's form. Then check:

- A record with latitude 91 is rejected.
- A valid record can be created, PATCHed and deleted.
- DELETE on an imported café returns 409.

## Issue #3 verification

| Check | Result |
| --- | --- |
| Django system check and `makemigrations --check` | No issues; no model changes requiring migrations |
| Automated tests | All 70 passed: 54 existing plus 16 API tests |
| Confirmed indoor-seat café filter on imported data | 91 records over HTTP, matching the Issue #2 count |
| Invalid filter value / anonymous POST over HTTP | 400 / 403 |

## Spatial search and area analysis (Issue #4)

All three operations run in PostGIS through GeoDjango. Python never calculates distances or containment. The query functions are in [spaces/spatial.py](spaces/spatial.py). All endpoints are public and read-only.

| Endpoint | Operation | PostGIS function |
| --- | --- | --- |
| `GET /api/spaces/nearby/?lat=&lng=&radius=` | Spaces within `radius` metres, nearest first | `ST_DistanceSphere` |
| `GET /api/spaces/nearest/?lat=&lng=` | Single closest matching space | `ST_DistanceSphere` + `LIMIT 1` |
| `GET /api/areas/coverage/` | Library and café counts per administrative area | `ST_CoveredBy` |

### Parameters and validation

- `lat` (−90..90) and `lng` (−180..180) are required decimal degrees in EPSG:4326 (WGS 84). NaN and infinity are rejected.
- `radius` is required for `nearby`. It is in metres, must be greater than 0 and at most 10,000.
- `nearby` and `nearest` accept the same `type` and facility filters as `/api/spaces/`. For example, `type=cafe&indoor_seating=true` matches only confirmed indoor seating. Filters apply before distance ordering, so `nearest` returns the closest *matching* space.
- Invalid values return `400 {"field": ["message"]}`.

### Responses

`nearby` returns a JSON list in the same format as `/api/spaces/`, plus `distance_m` (metres, one decimal place), ordered by distance. A search with no matches returns `200 []`.

`nearest` returns one study-space object with `distance_m`. If nothing matches, it returns `404 {"detail": "No study space matches these filters."}`.

`coverage` returns one row per area, ordered by name:

```json
[{"id": 1, "source_id": "central", "name": "CENTRAL", "library_count": 7, "cafe_count": 193, "total_count": 200}]
```

If no areas have been imported, `coverage` returns `200 []`.

### Coordinate systems, units and accuracy

- **Shared coordinate system:** stored points, stored boundaries and search points all use EPSG:4326, so no coordinate transformation happens at query time. Boundaries were converted from ITM (EPSG:2157) during the Issue #2 import.
- **Distance units:** for longitude/latitude geometry, GeoDjango's `Distance` uses `ST_DistanceSphere`, which returns metres. The spherical model differs from the more exact spheroid by less than about 0.5%, which is acceptable for walking-distance search.
- **Consistent distances:** one distance annotation is used to filter, sort and report results, so a returned `distance_m` never exceeds the requested radius.
- **Boundary edges:** `ST_CoveredBy` includes points exactly on an edge, so a space on a shared border counts in both areas. Spaces outside every area are not counted.

### Indexes and performance

| Operation | Index use | Measured cost |
| --- | --- | --- |
| Coverage | `ST_CoveredBy` uses the GiST index on `location` (a bitmap index scan in `EXPLAIN`). Each boundary is passed as a subquery, so polygons never leave the database. | 1 + number-of-areas queries (6 for DCC) |
| Nearby / nearest | `ST_DistanceSphere` is not index-assisted, so `EXPLAIN` shows a sequential scan. The distance for every row is computed inside PostgreSQL. | 1 query each |

For 657 rows the sequential scan takes milliseconds, and at this table size the planner would choose it anyway. Index-assisted radius searches would need a geography column or a projected (ITM) expression index. Neither is justified at this data size.

### Manual check

Windows PowerShell 5.1 passes a JSON array down the pipeline as one object, so wrap list requests in parentheses before `Select-Object`. It also decodes UTF-8 names as ISO-8859-1 ("CaffÃ¨" instead of "Caffè"). Browsers, JavaScript and PowerShell 7 decode them correctly.

```powershell
(Invoke-RestMethod "http://localhost:8000/api/spaces/nearby/?lat=53.3498&lng=-6.2603&radius=300&type=cafe&indoor_seating=true") | Select-Object name, distance_m
Invoke-RestMethod "http://localhost:8000/api/spaces/nearest/?lat=53.3498&lng=-6.2603&type=library" | Select-Object name, distance_m
Invoke-RestMethod "http://localhost:8000/api/areas/coverage/" | Format-Table
Invoke-WebRequest -UseBasicParsing "http://localhost:8000/api/spaces/nearby/?lat=53.3498&lng=-6.2603&radius=0"   # 400
```

To see the SQL and query plan:

```powershell
docker compose exec web /usr/local/bin/python manage.py shell -c "from spaces.models import StudySpace as S; from spaces.spatial import *; qs = spaces_within(S.objects.all(), search_point(53.3498, -6.2603), 500); print(qs.query); print(qs.explain())"
```

## Issue #4 verification

| Check | Result |
| --- | --- |
| Automated tests | All 84 passed: 70 existing plus 14 spatial tests |
| Known geometry | 0.005° and 0.01° of latitude returned about 556 m and 1,112 m (±1 m); radius 1,100 m excluded and 1,120 m included the 1,112 m point |
| Query counts (`assertNumQueries`) | Nearby 1, nearest 1, coverage 1 + areas |
| Generated SQL | `ST_DistanceSphere` for distance; `EXPLAIN` showed the sequential scan described above |
| Coverage on imported data | Central 200, North Central 52, North West 12, South Central 86, South East 307; total 657, equal to all imported records |
| HTTP smoke checks | Filtered nearby search 200 (12 confirmed-seat cafés within 300 m of the test point); nearest library 200; radius 0 → 400 |

## Development and attribution

Follow [AGENTS.md](AGENTS.md). Issue #4 is limited to spatial search and area-analysis endpoints; maps and the search UI belong to later issues. Imported data is source-reported and has not been independently surveyed.

AI assistance was used for the initial documentation and Issues #1–4 implementation. The student must review, verify and understand the work, and document assistance according to the module policy.
