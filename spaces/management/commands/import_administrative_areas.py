import json
import re

from django.contrib.gis.gdal import OGRGeometry
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.management.base import CommandError
from django.db import connection

from spaces.importers.common import SnapshotImportCommand, load_identities, read_json
from spaces.models import AdministrativeArea


class Command(SnapshotImportCommand):
    help = "Import DCC polygons, transforming the explicit source CRS into EPSG:4326."
    dataset = "dcc-administrative-areas"
    model = AdministrativeArea
    source_kind = "official"

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--repair-invalid", action="store_true",
            help="Explicitly repair invalid polygons with PostGIS ST_MakeValid and record provenance.",
        )

    def load_records(self, path):
        document = read_json(path)
        if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
            raise CommandError("Expected a GeoJSON FeatureCollection.")
        if not isinstance(document.get("features"), list):
            raise CommandError("GeoJSON features must be a list.")
        if document.get("crs") is not None:
            try:
                name = document["crs"]["properties"]["name"]
                match = re.search(r"EPSG(?::|::)(\d+)$", name, flags=re.I)
                if not match or int(match[1]) != self.entry["source_srid"]:
                    raise ValueError("File CRS does not match manifest source_srid.")
            except (KeyError, TypeError, ValueError) as exc:
                raise CommandError(f"Invalid or conflicting declared CRS: {exc}") from exc
        try:
            self.identities = load_identities(self.manifest_directory / self.entry["identity_map"])
        except KeyError as exc:
            raise CommandError("Boundary identity_map is required.") from exc
        return document["features"]

    def parse_record(self, row):
        if not isinstance(row, dict) or row.get("type") != "Feature":
            raise ValueError("Expected a GeoJSON Feature.")
        properties = row["properties"]
        if not isinstance(properties, dict) or not isinstance(properties.get("Name"), str):
            raise ValueError("Boundary properties need a text Name.")
        name = properties["Name"].strip()
        source_id = self.identities.get(name.casefold())
        if source_id is None:
            raise ValueError(f"Unmapped administrative area {name!r}.")
        shape = row["geometry"]
        if not isinstance(shape, dict) or shape.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError("Boundary must be a Polygon or MultiPolygon.")
        geometry = OGRGeometry(json.dumps(shape))
        # The official file has a Z ordinate, while our application is explicitly 2D.
        had_z = geometry.is_3d
        geometry.set_3d(False)
        geometry.srs = self.entry["source_srid"]
        geometry.transform(4326)
        boundary = geometry.geos
        if boundary.geom_type == "Polygon":
            boundary = MultiPolygon(boundary, srid=4326)
        attributes = {"properties": properties, "source_geometry_had_z": had_z}
        issues = []
        if not boundary.valid:
            reason = boundary.valid_reason
            if not self.options["repair_invalid"]:
                raise ValueError(f"Invalid boundary: {reason}; review before using --repair-invalid.")
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT ST_AsEWKB(ST_Multi(ST_CollectionExtract("
                    "ST_MakeValid(ST_GeomFromEWKB(%s)), 3)))",
                    [bytes(boundary.ewkb)],
                )
                boundary = GEOSGeometry(memoryview(cursor.fetchone()[0]))
            attributes["geometry_repair"] = {
                "method": "PostGIS ST_MakeValid; polygon extraction; ST_Multi",
                "original_validity_reason": reason,
            }
            issues.append(f"Explicit geometry repair applied: {reason}")
        return {
            "source_id": source_id, "name": name,
            "boundary": boundary,
            "source_attributes": attributes,
        }, issues
