from django.core.management.base import CommandError

from spaces.importers.common import SnapshotImportCommand, read_json, source_point
from spaces.importers.osm import parse_facilities
from spaces.models import StudySpace


class Command(SnapshotImportCommand):
    help = "Import all usable OSM cafe records in DCC, including unknown-seat cafes."
    dataset = "osm-cafes"
    model = StudySpace
    source_kind = "osm"
    uses_study_area = True

    def load_records(self, path):
        if self.entry["source_srid"] != 4326:
            raise CommandError("OSM coordinates must be EPSG:4326.")
        document = read_json(path)
        if not isinstance(document, dict) or not isinstance(document.get("elements"), list):
            raise CommandError("Expected an Overpass JSON document with an elements list.")
        if document.get("remark"):
            raise CommandError("Overpass reported an incomplete/error response; refusing partial import.")
        self.osm_base_timestamp = document.get("osm3s", {}).get("timestamp_osm_base")
        return document["elements"]

    def parse_record(self, row):
        element_type, element_id = row["type"], row["id"]
        if element_type not in {"node", "way", "relation"} or type(element_id) is not int or element_id <= 0:
            raise ValueError("A valid OSM element type and positive integer ID are required.")
        tags = row["tags"]
        if not isinstance(tags, dict) or tags.get("amenity") != "cafe":
            raise ValueError("Element must explicitly have amenity=cafe.")
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in tags.items()):
            raise ValueError("OSM tag keys and values must be strings.")
        name = tags.get("name", "").strip()
        if not name:
            raise ValueError("Cafe has no name; no real-world name will be invented.")
        coordinates = row if element_type == "node" else row["center"]
        if not isinstance(coordinates, dict):
            raise ValueError("Missing representative centre coordinates.")
        location = source_point(coordinates.get("lon"), coordinates.get("lat"))
        facilities, issues = parse_facilities(tags)
        address_parts = [
            " ".join(tags[key] for key in ("addr:housenumber", "addr:street") if tags.get(key)),
            tags.get("addr:city", ""), tags.get("addr:postcode", ""),
        ]
        return {
            "source_id": f"{element_type}/{element_id}",
            "source_url": f"https://www.openstreetmap.org/{element_type}/{element_id}",
            "name": name, "space_type": "cafe", "location": location,
            "location_method": "source_point" if element_type == "node" else "osm_center",
            "address": ", ".join(part for part in address_parts if part),
            "description": tags.get("description", ""),
            "source_attributes": {
                "tags": tags, "osm_type": element_type, "osm_id": element_id,
                "osm_base_timestamp": self.osm_base_timestamp,
            },
            **facilities,
        }, issues
