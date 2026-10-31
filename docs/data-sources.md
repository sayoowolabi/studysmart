# Data sources and import decisions

## Scope and schema

Initial coverage is the Dublin City Council (DCC) administrative area. The café download uses a broader bounding box; PostGIS `ST_Covers` (GeoDjango `boundary__covers`) tests each representative point against the complete imported DCC area set. Points on area boundaries are included. Unknown-seat cafés inside the study area are retained.

The database schema, geometry types, indexes and import pipeline are documented in [database.md](database.md).

## Sources and licensing

| Dataset | Source and content | CRS and licence |
| --- | --- | --- |
| Libraries | [Libraries DCC](https://data.smartdublin.ie/dataset/dublin-city-libraries), CSV resource `73b280a0-6938-4599-9fac-2b8a370ed7fd`; 24 named library/service records in the downloaded snapshot | Latitude/Longitude columns interpreted as EPSG:4326 and checked against Dublin boundaries; the CSV does not state a datum. Publisher reports Creative Commons Attribution (`cc-by`) without a version |
| Administrative areas | [Administrative Areas DCC](https://data.smartdublin.ie/dataset/administrative-areas-dcc), GeoJSON resource `13352b23-cc61-495a-9dc7-69416120e04d`; five committee areas | File explicitly declares EPSG:2157 (ITM), including Z ordinates; publisher reports `cc-by` without a version |
| Cafés | OpenStreetMap contributors, retrieved through the [Britain/Ireland Overpass instance](https://overpass.atownsend.org.uk/api/interpreter); `amenity=cafe` nodes, ways and relations | EPSG:4326; [Open Database Licence 1.0](https://www.openstreetmap.org/copyright) |
| University campus starting points | OpenStreetMap campus elements, looked up through Nominatim and Overpass on 2026-10-29; each element ID is recorded in [spaces/universities.py](../spaces/universities.py). Campuses are search origins only, not study-space records | EPSG:4326; Open Database Licence 1.0 |

Attribute DCC datasets to Dublin City Council / Smart Dublin and retain source links. Attribute OSM records to **© OpenStreetMap contributors** and retain the ODbL link. Preserve these per-source terms when exporting records; consult the ODbL terms before redistributing a combined database.

The DCC library description says last reviewed July 2021; the CSV resource was published September 2021. The administrative areas describe a 2019 revision. Catalogue metadata updates and our download time do not establish that the records were recently surveyed. The OSM database timestamp and our retrieval timestamp are also distinct.

No venue facilities have been independently surveyed by this implementation. A true value means explicit supporting source information, not a guarantee that the facility is currently available.

## Snapshot manifest and acquisition

`data/source-manifest.json` records file paths, source URLs, exact downloaded-file SHA-256 hashes, retrieval timestamps with timezone, licences and source EPSG codes. Café metadata also records the query and OSM database timestamp.

The snapshots in `data/raw/` are committed alongside the manifest and identity maps, so a fresh clone reproduces the recorded import exactly. A newly downloaded Overpass response would not match the recorded checksum. Committing the files also keeps an exact copy of the data behind the reported import counts. `.gitattributes` marks `data/raw/**` as `-text`, so Git never converts line endings and the SHA-256 checksums match on Windows and Linux. The snapshots stay excluded from the Docker image; Compose's source bind mount makes them available to the import commands. Redistribution is permitted under the sources' licences with the attribution given below and in the manifest. Synthetic test fixtures are separate and deliberately named fictional places; they are never loaded into the application database.

To refresh a snapshot from its source, download the files named in the manifest. In PowerShell:

```powershell
New-Item -ItemType Directory -Force data/raw | Out-Null
$manifest = Get-Content -Raw -Encoding UTF8 data/source-manifest.json | ConvertFrom-Json
Invoke-WebRequest -UseBasicParsing -Uri $manifest.'dcc-libraries'.source_url -OutFile data/raw/libraries.csv
Invoke-WebRequest -UseBasicParsing -Uri $manifest.'dcc-administrative-areas'.source_url -OutFile data/raw/areas.geojson
$query = $manifest.'osm-cafes'.query
$url = $manifest.'osm-cafes'.source_url + '?data=' + [uri]::EscapeDataString($query)
Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 60 -OutFile data/raw/cafes.json
Get-FileHash data/raw/libraries.csv,data/raw/areas.geojson,data/raw/cafes.json -Algorithm SHA256
```

The Overpass query is:

```overpass
[out:json][timeout:25];
nwr["amenity"="cafe"](53.2,-6.5,53.5,-5.9);
out center;
```

Overpass is a public service: cache downloads, respect the chosen instance's usage policy, and back off after errors. Several endpoints returned capacity errors or timed out during development; the regional instance returned the saved snapshot. There are no network calls in the import commands or tests.

A newly downloaded live snapshot can differ from the recorded hash. Review the new file, then update its manifest hash, actual retrieval time, source URL/query and source CRS as appropriate; do not disable checksum validation. Do not overwrite an existing snapshot before retaining the file required to reproduce a previous import. Overpass errors expressed through a JSON `remark` are rejected, even when some elements are present.

Always decode JSON as UTF-8. Windows PowerShell 5.1's default `Get-Content` encoding can corrupt accented names and currency symbols; the Python importers explicitly use UTF-8 with optional BOM. The commands read the original bytes rather than reserialising downloaded JSON in PowerShell.

## Identity and duplicates

Database uniqueness is enforced on `(source_dataset, source_id)` for both models.

- OSM identifiers include element type: `node/123`, `way/123` and `relation/123` are different identities.
- The library CSV has no persistent ID column. `data/library-identities.json` assigns 24 fixed local IDs with explicit source-name aliases. These are application-assigned IDs, not identifiers claimed to come from DCC.
- `data/area-identities.json` assigns fixed IDs to the five official area names.
- Never regenerate these IDs when names change. Add a reviewed name alias under the existing ID. New or ambiguous aliases require review; do not silently match by row position or mutable record hashes.
- Identical repeated source IDs in one file are counted once. Conflicting repeated IDs abort and roll back the command.
- Same-name imported records are reported as possible duplicates/shared names, not automatically merged. Chain branches and co-located library services can legitimately share names, addresses or coordinates.
- Source-ID uniqueness prevents repeat-import duplicates. It does not prove that different OSM elements represent different physical venues; such cases require manual review.
- No record is automatically deleted because it disappears from a later snapshot.

DCC includes the Central Library, Music Library and Business Information Centre as distinct source records, with some shared addresses. Counts describe source records and are not a verified count of distinct buildings.

## Geometry handling and data quality

Model validation rejects empty, non-finite, out-of-range, invalid or three-dimensional application geometry. Points are constructed as `Point(longitude, latitude, srid=4326)`; a latitude/longitude swap that remains globally legal is rejected by study-area containment.

Boundary importing:

1. Compare any declared file CRS with the explicit manifest EPSG code.
2. Use GDAL to deliberately remove the source Z dimension; record `source_geometry_had_z` alongside the untouched source properties.
3. Transform from the source CRS into EPSG:4326, then normalise Polygon to MultiPolygon.
4. Validate the result before saving.

The downloaded DCC file contains self-intersections in **NORTH WEST** and **CENTRAL**. The default command reports and rejects invalid features. For this inspected snapshot, `--repair-invalid` explicitly applies PostGIS `ST_MakeValid`, extracts polygon components and converts them to MultiPolygon. It records the original validity reason and repair method in `source_attributes.geometry_repair`, and reports each repair. The raw source file remains unchanged. Repaired geometry must still pass validation; this is not a claim that the source has been independently corrected.

Location imports require every area ID listed in the identity mapping, preventing a partially imported boundary set from silently excluding locations.

OSM node coordinates are retained directly. Way/relation `out center` values are approximate bounding-box centres, not entrances or guaranteed interior points. `location_method=osm_center` records this limitation; a representative centre near a boundary can affect inclusion. No geocoding or guessed coordinates are used.

Unnamed cafés and records without usable coordinates are reported and rejected. Unknown seating alone never causes rejection.

## Facility mapping

All five fields are nullable Boolean fields:

| Value | Meaning |
| --- | --- |
| `True` | Explicit positive source evidence |
| `False` | Explicit negative source evidence |
| SQL `NULL` / Python `None` | Missing, unclear, unsupported, conditional or conflicting information |

The original OSM tags are retained in `source_attributes.tags`. Libraries retain all CSV columns unchanged in `source_attributes`; descriptions mentioning computers or internet do not establish Wi-Fi, sockets or permission to use a laptop.

| Field | Mapping |
| --- | --- |
| `indoor_seating` | `indoor_seating=yes/no`; `bar_table` and unsupported values remain unknown |
| `outdoor_seating` | `yes/no`; documented seating-location values such as `sidewalk`, `terrace`, `patio` and `garden` indicate presence; supported positive semicolon combinations are accepted |
| `has_wifi` | `internet_access=wlan` (including supported combinations) and explicit `wifi=yes/free` establish presence; `internet_access=no` or `wifi=no` establish absence unless contradicted |
| `has_outlets` | Explicit `power_supply=yes/no`, or positive counts/yes for recognised mains socket types on the café itself (`socket:typea`–`typeo`, `schuko`, and `bs1363`, OSM's key for the Irish/UK type G socket); EV connectors, USB sockets, `electricity=yes` and `service:electricity` do not establish laptop outlets |
| `laptop_allowed` | Explicit `laptop=yes/no`; `restricted` and conditional restrictions remain unknown |

Generic `internet_access=yes`, wired internet and public computer terminals do not establish Wi-Fi. A zero count for one socket type does not prove that all outlets are absent. Conditional/seasonal tags and conflicting evidence remain unknown and are reported. Availability does not establish that a service is free.

Mapping references: [indoor seating](https://wiki.openstreetmap.org/wiki/Key:indoor_seating), [outdoor seating](https://wiki.openstreetmap.org/wiki/Key:outdoor_seating), [internet access](https://wiki.openstreetmap.org/wiki/Key:internet_access), [Wi-Fi](https://wiki.openstreetmap.org/wiki/Key:wifi), [power supply](https://wiki.openstreetmap.org/wiki/Key:power_supply), [socket types](https://wiki.openstreetmap.org/wiki/Key:socket:*), [laptop restrictions](https://wiki.openstreetmap.org/wiki/Key:laptop).

Confirmed indoor seating uses the exact ORM condition:

```python
StudySpace.objects.filter(space_type="cafe", indoor_seating=True)
```

The full café queryset still includes false/unknown seating. Outdoor seating does not qualify a café for an indoor-seat filter. The API's `indoor_seating=true` filter and the map's "Indoor seating" filter use the same condition.

## Importing and administrator corrections

```powershell
docker compose exec web /usr/local/bin/python manage.py migrate
docker compose exec web /usr/local/bin/python manage.py import_administrative_areas --repair-invalid --dry-run
docker compose exec web /usr/local/bin/python manage.py import_administrative_areas --repair-invalid
docker compose exec web /usr/local/bin/python manage.py import_libraries
docker compose exec web /usr/local/bin/python manage.py import_cafes
```

Repeat the last three commands to verify unchanged counts. All commands accept `--manifest PATH` and `--dry-run`. Paths inside a manifest resolve relative to that manifest's directory. Each command reports read/created/updated/unchanged/duplicate/outside/rejected/warning counts.

Malformed files/metadata fail before writes. Invalid individual records are reported and skipped. Conflicting duplicate identities abort the transaction; `--dry-run` rolls back all writes. Ordinary upserts validate records before saving. Repeat imports of the same file do not update `imported_at`; changed source-owned fields and provenance do.

The Django admin requires login and model permissions. It provides category and Yes/No/Unknown facility filters. Provenance and raw source attributes are read-only. For imported records, the import-owned name, type, location, address and description are also read-only, because the next import would overwrite manual edits.

Editing a facility in admin automatically protects **all five facility values**, records a verification time and requires evidence notes. Imports continue to refresh raw source attributes/provenance but preserve protected facility values. To resume source-controlled facility updates, save with the lock unchecked and no simultaneous facility changes, then rerun the import. Explicitly changing a protected value to unknown is supported.

This is intentionally a group-level lock, not a per-field history system. Source kind still describes the imported record's origin; the lock, notes and verification date distinguish its manually maintained facilities.

## Testing

Import and facility-mapping tests use temporary manifests and synthetic fixtures with a separate PostGIS test database, and make no network calls. They cover repeat and changed imports, source removals, manual protection, malformed inputs, non-finite and swapped coordinates, CRS transformation, Z removal and explicit geometry repair. See [testing.md](testing.md) for the full test suite and verified results.
