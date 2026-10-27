"""Import tests use deliberately fictional fixtures, never live network services."""
import csv
import hashlib
import json
import shutil
import tempfile
from io import StringIO
from pathlib import Path

from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from spaces.models import AdministrativeArea, FACILITY_FIELDS, StudySpace

FIXTURES = Path(__file__).parent / "fixtures"


class ImportTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for path in FIXTURES.iterdir():
            shutil.copyfile(path, self.root / path.name)
        self.manifest_path = self.root / "manifest.json"
        self.entries = {}
        for dataset, filename, extra in (
            ("dcc-administrative-areas", "areas.geojson", {"identity_map": "area-identities.json"}),
            ("dcc-libraries", "libraries.csv", {"identity_map": "library-identities.json"}),
            ("osm-cafes", "cafes.json", {}),
        ):
            self.entries[dataset] = {
                "file": filename, "source_url": "https://example.org/synthetic-fixture",
                "licence": "Synthetic test data, not a real dataset",
                "retrieved_at": "2026-01-01T00:00:00Z", "source_srid": 4326, **extra,
            }
        self.refresh_manifest()

    def refresh_manifest(self):
        for entry in self.entries.values():
            entry["sha256"] = hashlib.sha256((self.root / entry["file"]).read_bytes()).hexdigest()
        self.manifest_path.write_text(json.dumps(self.entries), encoding="utf-8")

    def run_import(self, name, **options):
        output, errors = StringIO(), StringIO()
        call_command(
            name, manifest=str(self.manifest_path), stdout=output, stderr=errors, **options,
        )
        return output.getvalue(), errors.getvalue()

    def seed_areas(self):
        self.run_import("import_administrative_areas")

    def update_json(self, filename, mutate):
        path = self.root / filename
        document = json.loads(path.read_text())
        mutate(document)
        path.write_text(json.dumps(document), encoding="utf-8")
        self.refresh_manifest()

    def library_rows(self, changes):
        path = self.root / "libraries.csv"
        with path.open(newline="") as source:
            reader = csv.DictReader(source)
            fields, rows = reader.fieldnames, list(reader)
        changes(rows)
        with path.open("w", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        self.refresh_manifest()

    def test_locations_require_boundaries(self):
        with self.assertRaisesMessage(CommandError, "Import DCC administrative areas"):
            self.run_import("import_libraries")

    def test_library_attributes_and_unknown_facilities_are_preserved(self):
        self.seed_areas()
        first, _ = self.run_import("import_libraries")
        self.assertIn("created=1", first)
        space = StudySpace.objects.get()
        self.assertEqual(space.space_type, "library")
        self.assertEqual(space.location, Point(-6.26, 53.35, srid=4326))
        self.assertEqual(space.source_attributes["OtherOfficialAttribute"], "Preserve this original value")
        self.assertEqual(space.source_kind, "official")
        for field in FACILITY_FIELDS:
            self.assertIsNone(getattr(space, field))
        imported_at = space.imported_at
        second, _ = self.run_import("import_libraries")
        self.assertIn("unchanged=1", second)
        space.refresh_from_db()
        self.assertEqual(space.imported_at, imported_at)
        self.assertEqual(StudySpace.objects.count(), 1)

    def test_library_alias_updates_same_record(self):
        self.seed_areas()
        self.run_import("import_libraries")
        pk = StudySpace.objects.get().pk
        self.library_rows(lambda rows: rows[0].update(
            CultureName="Renamed Fictional Library", Longitude="-6.27",
        ))
        output, _ = self.run_import("import_libraries")
        self.assertIn("updated=1", output)
        space = StudySpace.objects.get()
        self.assertEqual(space.pk, pk)
        self.assertEqual(space.name, "Renamed Fictional Library")
        self.assertEqual(space.location.x, -6.27)

    def test_missing_invalid_and_swapped_library_coordinates(self):
        self.seed_areas()
        for longitude, latitude in (("", "53.35"), ("-181", "53.35"), ("-6.26", "91"),
                                    ("nan", "53.35"), ("inf", "53.35"), ("53.35", "-6.26")):
            with self.subTest(longitude=longitude, latitude=latitude):
                self.library_rows(lambda rows: rows[0].update(Longitude=longitude, Latitude=latitude))
                output, _ = self.run_import("import_libraries")
                self.assertTrue("rejected=1" in output or "outside=1" in output)
                self.assertFalse(StudySpace.objects.exists())

    def test_unmapped_library_name_is_reported_without_inventing_identity(self):
        self.seed_areas()
        self.library_rows(lambda rows: rows[0].update(CultureName="Unreviewed New Name"))
        output, errors = self.run_import("import_libraries")
        self.assertIn("rejected=1", output)
        self.assertIn("Unmapped library", errors)
        self.assertFalse(StudySpace.objects.exists())

    def test_cafes_keep_unknown_seats_and_filter_only_confirmed_indoor(self):
        self.seed_areas()
        output, _ = self.run_import("import_cafes")
        self.assertIn("created=5", output)
        self.assertIn("duplicate=1", output)
        self.assertIn("outside=1", output)
        self.assertIn("rejected=1", output)
        self.assertEqual(StudySpace.objects.filter(space_type="cafe").count(), 5)
        self.assertEqual(
            set(StudySpace.objects.filter(space_type="cafe", indoor_seating=True).values_list("source_id", flat=True)),
            {"node/1", "way/1"},
        )
        self.assertTrue(StudySpace.objects.filter(source_id="node/2", indoor_seating__isnull=True).exists())
        self.assertTrue(StudySpace.objects.filter(source_id="node/3", indoor_seating=False, outdoor_seating=True).exists())
        self.assertEqual(StudySpace.objects.get(source_id="way/1").location_method, "osm_center")
        self.assertTrue(StudySpace.objects.filter(source_id="relation/1").exists())
        output, _ = self.run_import("import_cafes")
        self.assertIn("unchanged=5", output)
        self.assertEqual(StudySpace.objects.count(), 5)

    def test_changed_and_removed_tags_refresh_source_owned_values(self):
        self.seed_areas()
        self.run_import("import_cafes")
        original_pk = StudySpace.objects.get(source_id="node/1").pk
        def change(document):
            tags = document["elements"][0]["tags"]
            tags["indoor_seating"] = "no"
            tags.pop("internet_access")
        self.update_json("cafes.json", change)
        output, _ = self.run_import("import_cafes")
        self.assertIn("updated=1", output)
        space = StudySpace.objects.get(source_id="node/1")
        self.assertEqual(space.pk, original_pk)
        self.assertIs(space.indoor_seating, False)
        self.assertIsNone(space.has_wifi)
        self.assertNotIn("internet_access", space.source_attributes["tags"])

    def test_manual_facility_lock_survives_reimport_and_can_be_released(self):
        self.seed_areas()
        self.run_import("import_cafes")
        space = StudySpace.objects.get(source_id="node/2")
        space.indoor_seating = True
        space.facility_import_locked = True
        space.facility_verification_notes = "Fictional verification for a synthetic test."
        space.full_clean()
        space.save()
        self.run_import("import_cafes")
        space.refresh_from_db()
        self.assertIs(space.indoor_seating, True)
        space.facility_import_locked = False
        space.save()
        self.run_import("import_cafes")
        space.refresh_from_db()
        self.assertIsNone(space.indoor_seating)

    def test_missing_snapshot_records_are_not_deleted(self):
        self.seed_areas()
        self.run_import("import_cafes")
        self.update_json("cafes.json", lambda document: document.update(elements=[]))
        self.run_import("import_cafes")
        self.assertEqual(StudySpace.objects.count(), 5)

    def test_conflicting_duplicate_ids_roll_back_all_writes(self):
        self.seed_areas()
        def conflict(document):
            copy = json.loads(json.dumps(document["elements"][0]))
            copy["tags"]["name"] = "A conflicting name"
            document["elements"].append(copy)
        self.update_json("cafes.json", conflict)
        with self.assertRaisesMessage(CommandError, "Conflicting duplicate source ID"):
            self.run_import("import_cafes")
        self.assertFalse(StudySpace.objects.exists())

    def test_checksum_and_partial_overpass_response_fail_before_writes(self):
        self.seed_areas()
        (self.root / "cafes.json").write_text("modified", encoding="utf-8")
        with self.assertRaisesMessage(CommandError, "checksum"):
            self.run_import("import_cafes")
        shutil.copyfile(FIXTURES / "cafes.json", self.root / "cafes.json")
        self.update_json("cafes.json", lambda document: document.update(remark="runtime timeout"))
        with self.assertRaisesMessage(CommandError, "incomplete/error"):
            self.run_import("import_cafes")
        self.assertFalse(StudySpace.objects.exists())

    def test_malformed_csv_headers_and_missing_timezone_are_rejected(self):
        self.seed_areas()
        (self.root / "libraries.csv").write_text("wrong,headers\n1,2\n", encoding="utf-8")
        self.refresh_manifest()
        with self.assertRaisesMessage(CommandError, "headers"):
            self.run_import("import_libraries")
        self.entries["osm-cafes"]["retrieved_at"] = "2026-01-01"
        self.refresh_manifest()
        with self.assertRaisesMessage(CommandError, "timezone"):
            self.run_import("import_cafes")

    def test_ambiguous_identity_mapping_is_rejected(self):
        (self.root / "library-identities.json").write_text(
            json.dumps({"id-1": ["Fictional Library"], "id-2": ["Fictional Library"]}),
        )
        with self.assertRaisesMessage(CommandError, "Ambiguous identity"):
            self.run_import("import_libraries")

    def test_dry_run_does_not_persist_records(self):
        output, _ = self.run_import("import_administrative_areas", dry_run=True)
        self.assertIn("DRY RUN", output)
        self.assertFalse(AdministrativeArea.objects.exists())

    def test_boundary_polygon_is_normalised_and_repeatable(self):
        self.run_import("import_administrative_areas")
        area = AdministrativeArea.objects.get()
        self.assertEqual(area.boundary.geom_type, "MultiPolygon")
        self.assertEqual(area.boundary.srid, 4326)
        self.assertTrue(area.boundary.covers(Point(-6.26, 53.35, srid=4326)))
        output, _ = self.run_import("import_administrative_areas")
        self.assertIn("unchanged=1", output)
        self.assertEqual(AdministrativeArea.objects.count(), 1)

    def test_projected_boundary_is_transformed_not_relabelled(self):
        self.entries["dcc-administrative-areas"]["source_srid"] = 2157
        def projected(document):
            document["crs"]["properties"]["name"] = "urn:ogc:def:crs:EPSG::2157"
            document["features"][0]["geometry"]["coordinates"] = [[
                [710000, 730000], [720000, 730000], [720000, 740000],
                [710000, 740000], [710000, 730000],
            ]]
        self.update_json("areas.geojson", projected)
        self.run_import("import_administrative_areas")
        area = AdministrativeArea.objects.get()
        self.assertEqual(area.source_srid, 2157)
        xmin, ymin, xmax, ymax = area.boundary.extent
        self.assertTrue(-6.6 < xmin < xmax < -6.0)
        self.assertTrue(53.2 < ymin < ymax < 53.6)

    def test_conflicting_crs_is_rejected(self):
        self.entries["dcc-administrative-areas"]["source_srid"] = 2157
        self.refresh_manifest()
        with self.assertRaisesMessage(CommandError, "CRS"):
            self.run_import("import_administrative_areas")
        self.assertFalse(AdministrativeArea.objects.exists())

    def test_source_z_is_explicitly_removed_and_recorded(self):
        def add_z(document):
            ring = document["features"][0]["geometry"]["coordinates"][0]
            document["features"][0]["geometry"]["coordinates"][0] = [point + [0] for point in ring]
        self.update_json("areas.geojson", add_z)
        self.run_import("import_administrative_areas")
        area = AdministrativeArea.objects.get()
        self.assertFalse(area.boundary.hasz)
        self.assertTrue(area.source_attributes["source_geometry_had_z"])
        self.assertEqual(area.source_attributes["properties"]["Name"], "Fixture Area")

    def test_invalid_boundary_is_rejected(self):
        def invalid(document):
            document["features"][0]["geometry"]["coordinates"] = [[
                [-6.4, 53.2], [-6.1, 53.4], [-6.4, 53.4], [-6.1, 53.2], [-6.4, 53.2],
            ]]
        self.update_json("areas.geojson", invalid)
        output, _ = self.run_import("import_administrative_areas")
        self.assertIn("rejected=1", output)
        self.assertFalse(AdministrativeArea.objects.exists())

    def test_explicit_boundary_repair_is_valid_and_records_provenance(self):
        def invalid(document):
            document["features"][0]["geometry"]["coordinates"] = [[
                [-6.4, 53.2], [-6.1, 53.4], [-6.4, 53.4], [-6.1, 53.2], [-6.4, 53.2],
            ]]
        self.update_json("areas.geojson", invalid)
        output, errors = self.run_import("import_administrative_areas", repair_invalid=True)
        self.assertIn("created=1", output)
        self.assertIn("Explicit geometry repair", errors)
        area = AdministrativeArea.objects.get()
        self.assertTrue(area.boundary.valid)
        self.assertEqual(area.boundary.srid, 4326)
        self.assertIn("ST_MakeValid", area.source_attributes["geometry_repair"]["method"])

    def test_incomplete_boundary_set_blocks_location_import(self):
        self.seed_areas()
        (self.root / "area-identities.json").write_text(json.dumps({
            "fixture-area": ["Fixture Area"], "missing-area": ["Missing Area"],
        }))
        with self.assertRaisesMessage(CommandError, "Missing IDs: ['missing-area']"):
            self.run_import("import_libraries")

    def test_invalid_osm_identity_and_missing_centres_are_rejected(self):
        def invalid(document):
            document["elements"] = [
                {"type": "node", "id": True, "lat": 53.35, "lon": -6.26,
                 "tags": {"amenity": "cafe", "name": "Fictional Boolean ID"}},
                {"type": "way", "id": 10, "tags": {"amenity": "cafe", "name": "Fictional Missing Centre"}},
                {"type": "node", "id": 11, "lat": 53.35, "lon": -6.26,
                 "tags": {"amenity": "restaurant", "name": "Fictional Non Cafe"}},
            ]
        self.seed_areas()
        self.update_json("cafes.json", invalid)
        output, _ = self.run_import("import_cafes")
        self.assertIn("rejected=3", output)
        self.assertFalse(StudySpace.objects.exists())

    def test_same_name_is_reported_without_automatically_merging(self):
        self.seed_areas()
        def change(document):
            document["elements"][1]["tags"]["name"] = "Fictional Indoor Cafe"
            document["elements"].pop()  # Remove the formerly identical repeated node/2.
        self.update_json("cafes.json", change)
        _, errors = self.run_import("import_cafes")
        self.assertIn("Review possible duplicate/shared name", errors)
        self.assertEqual(StudySpace.objects.count(), 5)
