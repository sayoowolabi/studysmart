# REST API

The API is built with Django REST Framework. All examples below are real responses from the running application with the committed data (captured on 2026-10-30). Long lists are shortened, as marked.

- **Base URL (local):** `http://localhost:8000`
- **Format:** JSON. Opening an endpoint in a browser shows DRF's browsable API; append `?format=json` or `.json` (for example `/api/spaces.json`) to force JSON.
- **Coordinates:** EPSG:4326 decimal degrees. Study spaces use `latitude` and `longitude` fields; area boundaries use GeoJSON (`[longitude, latitude]`).
- **Distances:** metres, calculated by PostGIS.

## Authentication and permissions

| Operation | Who |
| --- | --- |
| Every `GET` | Anyone, no login |
| `POST /api/spaces/` | Users with the `spaces.add_studyspace` permission |
| `PATCH /api/spaces/{id}/` | Users with `spaces.change_studyspace` |
| `DELETE /api/spaces/{id}/` | Users with `spaces.delete_studyspace` |

Authentication uses Django sessions: log in at `/admin/`, then use the browsable API, which includes the CSRF token. Writes without a valid CSRF token are rejected. HTTP Basic authentication is disabled because the development server runs over plain HTTP. Superusers have all permissions.

## Endpoints

| Method | URL | Purpose |
| --- | --- | --- |
| GET | [`/api/`](#get-api) | Browsable index of the study-space endpoints |
| GET | [`/api/spaces/`](#get-apispaces) | List study spaces, with filters |
| GET | [`/api/spaces/{id}/`](#get-apispacesid) | One study space |
| POST | [`/api/spaces/`](#post-apispaces) | Create |
| PATCH | [`/api/spaces/{id}/`](#patch-apispacesid) | Update |
| DELETE | [`/api/spaces/{id}/`](#delete-apispacesid) | Delete |
| GET | [`/api/spaces/nearby/`](#get-apispacesnearby) | Radius search |
| GET | [`/api/spaces/nearest/`](#get-apispacesnearest) | Nearest study space |
| GET | [`/api/areas/`](#get-apiareas) | Administrative-area boundaries (GeoJSON) |
| GET | [`/api/areas/coverage/`](#get-apiareascoverage) | Libraries and cafés per area |

`PUT` is not offered (405); use `PATCH`. The area endpoints are read-only.

---

### GET /api/

The DRF router's index. It lists the router's endpoint (`spaces`); the area endpoints are separate views and are listed above.

```json
{"spaces": "http://localhost:8000/api/spaces/"}
```

### Study-space object

Every study-space endpoint returns objects with these fields:

```json
{
  "id": 639,
  "name": "Filo",
  "space_type": "cafe",
  "latitude": 53.3651788,
  "longitude": -6.2714909,
  "location_method": "osm_center",
  "address": "20 Prospect Road, Dublin",
  "description": "",
  "indoor_seating": true,
  "outdoor_seating": true,
  "has_wifi": null,
  "has_outlets": true,
  "laptop_allowed": null,
  "facility_import_locked": false,
  "facility_verification_notes": "",
  "facility_verified_at": null,
  "source_dataset": "osm-cafes",
  "source_id": "way/970119309",
  "source_kind": "osm",
  "source_url": "https://www.openstreetmap.org/way/970119309",
  "source_licence": "Open Database Licence (ODbL) 1.0; OpenStreetMap contributors",
  "source_retrieved_at": "2026-10-27T12:23:13.194166Z",
  "imported_at": "2026-10-29T18:39:26.818066Z"
}
```

| Field | Notes |
| --- | --- |
| `space_type` | `library` or `cafe` |
| `latitude`, `longitude` | Stored together as a PostGIS point |
| `location_method` | `source_point`, `osm_center` (approximate centre) or `manual` |
| `indoor_seating`, `outdoor_seating`, `has_wifi`, `has_outlets`, `laptop_allowed` | `true` confirmed, `false` confirmed absent, `null` **unknown** |
| `facility_import_locked`, `facility_verified_at` | Read-only; set when facilities are corrected |
| `source_*`, `imported_at` | Read-only provenance and attribution |

The search endpoints add `distance_m` (metres, one decimal place). The raw `source_attributes` are not exposed.

---

### GET /api/spaces/

Lists all study spaces, ordered by name. Not paginated.

| Query parameter | Values | Effect |
| --- | --- | --- |
| `type` | `library`, `cafe` | Only that type |
| `indoor_seating`, `outdoor_seating`, `has_wifi`, `has_outlets`, `laptop_allowed` | `true`, `false`, `unknown` (case-insensitive) | `true` matches only confirmed values; `unknown` matches only unknown |

Filters combine with AND. Example: `GET /api/spaces/?type=cafe&indoor_seating=true` returns the 91 cafés with confirmed indoor seating.

### GET /api/spaces/{id}/

Returns one study-space object, or 404:

```json
{"detail": "No StudySpace matches the given query."}
```

### GET /api/spaces/nearby/

Study spaces within a radius of a point, nearest first. PostGIS: `ST_DistanceSphere` for filtering, ordering and the reported distance.

| Parameter | Required | Rules |
| --- | --- | --- |
| `lat` | yes | −90 to 90, finite |
| `lng` | yes | −180 to 180, finite |
| `radius` | yes | Metres, greater than 0, at most 10,000 |
| `type` and facility filters | no | As for `/api/spaces/` |

`GET /api/spaces/nearby/?lat=53.34371&lng=-6.25443&radius=300&type=cafe&indoor_seating=true` (Trinity College Dublin; 12 results, first shown):

```json
[
  {
    "id": 147,
    "name": "O'Briens",
    "space_type": "cafe",
    "latitude": 53.3421624,
    "longitude": -6.2550835,
    "address": "3 Nassau Street, Dublin",
    "indoor_seating": true,
    "outdoor_seating": false,
    "has_wifi": false,
    "has_outlets": null,
    "laptop_allowed": null,
    "source_id": "node/2681836817",
    "…": "other study-space fields",
    "distance_m": 177.5
  }
]
```

No matches returns `200 []`.

### GET /api/spaces/nearest/

The single closest study space matching the filters, with no distance limit. PostGIS: `ST_DistanceSphere` with `LIMIT 1`. Parameters are `lat` and `lng` (required, as above) and the optional `type` and facility filters. Filters are applied before the nearest is chosen.

`GET /api/spaces/nearest/?lat=53.34371&lng=-6.25443&type=library`:

```json
{
  "id": 5,
  "name": "Dublin City Library and Archive",
  "space_type": "library",
  "latitude": 53.34309087,
  "longitude": -6.245279595,
  "address": "138-144 Pearse Street, D02HE37",
  "indoor_seating": null,
  "…": "other study-space fields",
  "distance_m": 611.3
}
```

If nothing matches, it returns 404:

```json
{"detail": "No study space matches these filters."}
```

### POST /api/spaces/

Creates a study space. `name`, `space_type`, `latitude` and `longitude` are required; `address`, `description` and the facilities are optional (facilities default to unknown). The record is always created as `source_kind = "manual"`: read-only fields sent by the client (such as `source_kind`, `source_id` or `facility_import_locked`) are ignored.

```json
{"name": "Example Study Room", "space_type": "library", "latitude": 53.3438, "longitude": -6.2546, "address": "Example address"}
```

Response `201 Created`:

```json
{
  "id": 658,
  "name": "Example Study Room",
  "space_type": "library",
  "latitude": 53.3438,
  "longitude": -6.2546,
  "location_method": "manual",
  "address": "Example address",
  "description": "",
  "indoor_seating": null,
  "outdoor_seating": null,
  "has_wifi": null,
  "has_outlets": null,
  "laptop_allowed": null,
  "facility_import_locked": false,
  "facility_verification_notes": "",
  "facility_verified_at": null,
  "source_dataset": "manual",
  "source_id": "449107ea-37fa-498d-9d85-dc7957bdeded",
  "source_kind": "manual",
  "source_url": "",
  "source_licence": "",
  "source_retrieved_at": null,
  "imported_at": null
}
```

### PATCH /api/spaces/{id}/

Partial update. Sending only `latitude` or only `longitude` keeps the other coordinate. Rules:

- **Changing a facility** requires `facility_verification_notes` (the evidence). It then locks all five facilities against future imports and records `facility_verified_at`.
- **Imported records** (`source_kind` `official` or `osm`): `name`, `space_type`, the coordinates, `address` and `description` cannot be changed, because the next import would overwrite them. Correct the source data instead.

### DELETE /api/spaces/{id}/

Deletes a manually created record (`204 No Content`). Imported records return `409 Conflict`, because the next import would recreate them.

---

### GET /api/areas/

Administrative-area boundaries as a GeoJSON `FeatureCollection`, ordered by name. PostGIS: `ST_AsGeoJSON`, coordinates rounded to five decimal places (about 1 m). The current data has 5 features (about 330 KB).

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": 5,
      "geometry": {"type": "MultiPolygon", "coordinates": [[[[-6.19791, 53.34527], [-6.19794, 53.34532], "…"]]]},
      "properties": {"source_id": "central", "name": "CENTRAL"}
    }
  ]
}
```

With no areas imported, `features` is an empty list.

### GET /api/areas/coverage/

Library and café counts for each area, ordered by name. PostGIS: `ST_CoveredBy` (a space on a shared boundary counts in both areas; spaces outside every area are not counted). These are dataset-wide counts and are not affected by any filter.

```json
[
  {"id": 5, "source_id": "central", "name": "CENTRAL", "library_count": 7, "cafe_count": 193, "total_count": 200},
  {"id": 1, "source_id": "north-central", "name": "NORTH CENTRAL", "library_count": 4, "cafe_count": 48, "total_count": 52},
  {"id": 4, "source_id": "north-west", "name": "NORTH WEST", "library_count": 2, "cafe_count": 10, "total_count": 12},
  {"id": 3, "source_id": "south-central", "name": "SOUTH CENTRAL", "library_count": 3, "cafe_count": 83, "total_count": 86},
  {"id": 2, "source_id": "south-east", "name": "SOUTH EAST", "library_count": 8, "cafe_count": 299, "total_count": 307}
]
```

---

## Errors

Validation errors use DRF's standard shape, `{"field": ["message"]}`; other errors use `{"detail": "message"}`.

| Status | When | Example response |
| --- | --- | --- |
| 400 | Missing or invalid search parameters | `{"lat": ["This field is required."], "lng": ["This field is required."], "radius": ["This field is required."]}` |
| 400 | Radius out of range | `{"radius": ["Must be greater than 0 metres."]}` or `{"radius": ["Ensure this value is less than or equal to 10000."]}` |
| 400 | Coordinates out of range | `{"lat": ["Ensure this value is less than or equal to 90."]}` |
| 400 | Unknown type or filter value | `{"type": ["Use one of: library, cafe."]}`, `{"indoor_seating": ["Use true, false or unknown."]}` |
| 400 | Invalid write | `{"space_type": ["\"university\" is not a valid choice."], "latitude": ["Ensure this value is less than or equal to 90."], "has_wifi": ["Must be a valid boolean."]}` |
| 400 | Facility change without evidence | `{"facility_verification_notes": ["Explain the evidence for protected facility values."]}` |
| 400 | Changing a source-owned field of an imported record | `{"name": ["This value comes from osm-cafes and would be overwritten by the next import."]}` |
| 400 | Malformed JSON | `{"detail": "JSON parse error - …"}` |
| 403 | Not logged in, missing permission or missing CSRF token | `{"detail": "Authentication credentials were not provided."}` |
| 404 | Unknown ID, or no nearest match | `{"detail": "No StudySpace matches the given query."}`, `{"detail": "No study space matches these filters."}` |
| 405 | `PUT`, or any write to a read-only endpoint | `{"detail": "Method \"PUT\" not allowed."}` |
| 409 | Deleting an imported record | `{"detail": "Imported records cannot be deleted because the next import would recreate them. Only manually created records can be deleted."}` |

Latitude, longitude and radius also reject `NaN` and infinity. Unknown query parameters are ignored.
