# Testing and quality assurance

StudySmart has two automated suites, both run in continuous integration:

| Suite | Location | Size | Runs against |
| --- | --- | --- | --- |
| Django tests | [spaces/tests/](../spaces/tests/) | 129 tests | A separate PostGIS test database created and removed by Django |
| Browser tests | [frontend-tests/map-ui.test.mjs](../frontend-tests/map-ui.test.mjs) | 39 checks | The running site with the committed data imported, in headless Chrome or Edge |

## Running the tests

```powershell
# Django tests (inside the web container)
docker compose exec web /usr/local/bin/python manage.py test spaces
docker compose exec web /usr/local/bin/python manage.py test spaces --shuffle    # random order, as in CI

# System and migration checks
docker compose exec web /usr/local/bin/python manage.py check --database default
docker compose exec web /usr/local/bin/python manage.py makemigrations --check --dry-run

# Browser tests (on the host: Node 22+, and Chrome, Chromium or Edge; site running with data imported)
node frontend-tests/map-ui.test.mjs
```

The Django test database is separate from the application database and is deleted afterwards. Import tests use small synthetic fixtures (fictional places) copied to a temporary folder. No test makes a network call.

## Django tests

| File | Tests | What is verified |
| --- | --- | --- |
| [test_models.py](../spaces/tests/test_models.py) | 12 | Both space types and the three facility states; required fields and coordinate validation; the unique-source and valid-type **database constraints**; OSM element types as distinct identities; facility locks require evidence; boundary validation; admin permissions, read-only provenance and the facility-correction workflow |
| [test_api.py](../spaces/tests/test_api.py) | 27 | Public list and detail; 404; latitude/longitude not swapped; unknown returned as `null`; type and `true`/`false`/`unknown` filters; invalid filters (400); anonymous, unprivileged and CSRF-less writes refused (403); **each operation needs its own permission**; an anonymous write sweep of every endpoint (403/405, nothing changed); create, update and partial coordinate update; invalid values (400) leaving records unchanged; read-only provenance cannot be spoofed; imported-record protection (400, 409); PUT 405; malformed JSON 400 |
| [test_spatial.py](../spaces/tests/test_spatial.py) | 23 | Radius search with **known distances** (0.005° and 0.01° of latitude ≈ 556 m and 1,112 m, ±1 m) and the radius edge; combined type and facility filters; unknown seating in a radius search; empty results; invalid and missing parameters; radius limits; nearest with distance and filters, 404; containment counts with a point **on a shared border** counted in both areas; an **L-shaped area** that excludes a point inside its bounding box and a point 0.7 m outside its edge; boundary GeoJSON in `[longitude, latitude]` order with 5-decimal rounding; read-only endpoints; number of SQL queries per request |
| [test_imports.py](../spaces/tests/test_imports.py) | 23 | **Repeat imports create no duplicates** (`unchanged`); library name aliases keep the same record; missing, invalid and swapped coordinates; changed source tags update records; **locked facilities survive re-import**; records missing from a newer snapshot are not deleted; conflicting duplicate IDs roll back the whole import; checksum mismatch and partial Overpass responses fail before any write; dry runs persist nothing; **ITM to EPSG:4326 transformation**; conflicting CRS rejected; Z values removed and recorded; invalid boundaries rejected unless explicitly repaired; incomplete area sets block location imports |
| [test_facilities.py](../spaces/tests/test_facilities.py) | 12 | OSM tag mapping: missing tags stay unknown; explicit yes/no; supported seating values; conflicting, conditional and unrecognised values stay unknown; Wi-Fi needs wireless evidence; socket counts and the `bs1363` socket key; Wi-Fi does not imply laptop permission |
| [test_environment.py](../spaces/tests/test_environment.py) | 28 | PostGIS is available (`PostGIS_Version()`); `DEBUG` defaults to off and accepts only `True`/`False`; missing or placeholder secrets and a missing database password stop Django; default allowed hosts are local only; unknown hosts get 400; **security headers** on pages and the API; the map page: API URLs from `{% url %}`, labelled controls, filter values matching API parameters, radius choices within the API limit, pinned CDN files with integrity hashes, OSM attribution, **no module inserting HTML**, one `h1` and one live region, self-hosted font with its licence, facility filters disabled when nothing confirms them |
| [test_universities.py](../spaces/tests/test_universities.py) | 4 | Campus points are valid, in Dublin and traceable to an OSM element; only UCD has a coverage note; the selector renders each campus's coordinates; campuses are not study spaces |

**Spatial tests run against real PostGIS.** The database engine is fixed to `django.contrib.gis.db.backends.postgis` in settings (there is no SQLite fallback); `test_postgis_is_available` queries `PostGIS_Version()`; and the spatial assertions would fail without PostGIS's distance and containment functions.

## Browser tests

[frontend-tests/map-ui.test.mjs](../frontend-tests/map-ui.test.mjs) drives a headless Chromium-based browser through the Chrome DevTools Protocol, using only Node's built-in `WebSocket` (no npm packages). Expected values are fetched from the running API, so the checks follow the imported data. The 39 checks cover:

- the all-spaces map, the self-hosted font, one `h1` and one live region;
- campus search: the top 10 cards in the **same order and with the same IDs as the API**, matching numbered markers, the starting-point pin;
- **card facility chips matching true/false/unknown in the API**;
- card click and marker click highlighting each other; overlapping markers stacked nearest on top;
- filters and *Reset filters*; the UCD empty state with *Show nearest match* and *Search a wider area*; no type selected;
- geolocation granted, denied and unavailable (emulated);
- *Pick on map* with a marker and with a map point;
- rapid campus changes (superseded requests cancelled; the last one wins);
- a simulated HTTP 500 and recovery;
- desktop, tablet (768 px) and phone (390 px) layouts with no sideways scrolling, collapsed filters and the map on the first screen, and a card click scrolling the map into view;
- no JavaScript errors outside the deliberate failure.

The script exits with code 1 on any failure. Optional settings are `STUDYSMART_URL`, `BROWSER`, `BLOCK_MAP_TILES=1` and `SCREENSHOT_DIR` (see the file header).

## Continuous integration

[.github/workflows/tests.yml](../.github/workflows/tests.yml) runs on every push and pull request:

1. Write a test-only `.env` (throwaway values, `DJANGO_DEBUG=False`; no repository secrets).
2. Validate `docker-compose.yml` and build the Django image from the project's `Dockerfile`.
3. Start PostGIS and wait for its health check.
4. `manage.py check`, `makemigrations --check --dry-run`, then `manage.py test spaces --shuffle`.
5. Start the web server with `DJANGO_DEBUG=True` (the development server serves static files only in debug mode), import the committed snapshots, and run the browser tests in the runner's Chrome with OpenStreetMap tiles blocked.
6. On failure, keep the browser screenshots and service logs. Always remove the CI containers.

Because CI uses the project's own Compose stack, it tests the same Python, GDAL, GEOS and PostGIS versions as local development.

### Intermittent failures found and fixed

Running the suites repeatedly in CI exposed three order- and timing-dependent problems. Each was reproduced or diagnosed before being fixed; none was in the application:

| Symptom | Cause | Fix |
| --- | --- | --- |
| `test_nearest_with_distance`: "2 queries executed, 1 expected", only in some random orders | The first `Distance` query in a process makes GeoDjango read EPSG:4326's units from `spatial_ref_sys` once. Reproduced locally with the failing CI seed (`--shuffle 2776660069`) | `setUpModule` in `test_spatial.py` loads that cache, so query counts no longer depend on test order |
| Browser test could not click a result marker in *Pick on map* mode | The test waited for a summary text that the previous step had already shown, and could act before the new search and map animation finished. Added diagnostics later showed the markers out of view | Wait for that search to finish, centre the map on result 1 through its card, and click only a marker that is visible and no longer moving |
| Browser did not start within 10 s on some runners | Slow Chrome start-up on shared runners | Allow 30 s; fail immediately with the browser's own output if it crashes |

## Verified results

| Date | Check | Result |
| --- | --- | --- |
| 2026-10-29 | CI on the final pull request (#18), commit `e7b4e09`: push and PR runs plus four re-runs | **6 of 6 passed**: 129 Django tests in a different random order each time, 39 of 39 browser checks |
| 2026-10-29 | CI on `main` after merging, commit `4efc69c` | Passed |
| 2026-10-30 | Clean installation from a fresh clone of `main` (`4efc69c`) | `check` and `pip check` clean; 129 tests passed in random order; 39 of 39 browser checks; see [deployment.md](deployment.md#clean-installation-verification) |
| 2026-10-30 | Development environment | 129 tests passed; `makemigrations --check`: no changes |

## What is not automated

These need a person and a real browser: keyboard-only use with a screen reader, real phones and tablets (the Compose setup only listens on `localhost`, so use browser device emulation), the pgAdmin interface, and the Django admin's map widgets. The Django tests do cover the admin's permissions and validation rules.
