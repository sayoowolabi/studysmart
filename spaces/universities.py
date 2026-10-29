"""University campuses offered as search starting points on the map.

Campuses are search origins only: they are not study spaces and are never stored
or returned by the API. Each point is the representative point of the named
OpenStreetMap campus element, retrieved on 2026-10-29 through Nominatim and
Overpass (© OpenStreetMap contributors, ODbL), rounded to five decimal places.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Campus:
    slug: str
    name: str
    latitude: float
    longitude: float
    osm_element: str
    coverage_note: str = ""


CAMPUSES = (
    Campus("dbs", "Dublin Business School (Aungier Street)", 53.34052, -6.26544, "node/651804747"),
    Campus("dcu-glasnevin", "Dublin City University (Glasnevin)", 53.38498, -6.25745, "way/135230135"),
    Campus("griffith", "Griffith College Dublin (South Circular Road)", 53.33078, -6.27836, "way/62231120"),
    Campus("ncad", "National College of Art and Design", 53.34348, -6.27859, "way/52375058"),
    Campus("rcsi", "RCSI (St Stephen's Green)", 53.33916, -6.26270, "relation/4203256"),
    Campus("tud-grangegorman", "TU Dublin (Grangegorman)", 53.35515, -6.28082, "relation/11223485"),
    Campus("tcd", "Trinity College Dublin", 53.34371, -6.25443, "way/311466843"),
    Campus(
        "ucd-belfield", "University College Dublin (Belfield)", 53.30685, -6.22463, "relation/4260436",
        coverage_note=(
            "UCD Belfield is outside the Dublin City Council area that the current data covers, "
            "so fewer nearby study spaces may appear. Try a larger search radius."
        ),
    ),
)
