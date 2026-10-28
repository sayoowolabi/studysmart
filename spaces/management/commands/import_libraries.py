import csv

from django.core.management.base import CommandError

from spaces.importers.common import SnapshotImportCommand, load_identities, source_point
from spaces.models import FACILITY_FIELDS, StudySpace


class Command(SnapshotImportCommand):
    help = "Import the official DCC library CSV snapshot; unknown facilities stay null."
    dataset = "dcc-libraries"
    model = StudySpace
    source_kind = "official"
    uses_study_area = True

    def load_records(self, path):
        if self.entry["source_srid"] != 4326:
            raise CommandError("The library CSV latitude/longitude columns must be EPSG:4326.")
        try:
            self.identities = load_identities(self.manifest_directory / self.entry["identity_map"])
            with path.open(encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source)
                required = {"CultureName", "Latitude", "Longitude"}
                headers = reader.fieldnames or []
                if not required <= set(headers) or len(headers) != len(set(headers)):
                    raise CommandError("Library CSV headers are missing or duplicated.")
                return list(reader)
        except (OSError, UnicodeError, csv.Error, KeyError) as exc:
            raise CommandError(f"Cannot read library CSV/identity mapping: {exc}") from exc

    def parse_record(self, row):
        if None in row or any(value is None for value in row.values()):
            raise ValueError("CSV row has missing or extra columns.")
        name = row["CultureName"].strip()
        source_id = self.identities.get(name.casefold())
        if source_id is None:
            raise ValueError(f"Unmapped library name {name!r}; review the stable identity mapping.")
        address = ", ".join(row.get(key, "").strip() for key in
                            ("PostalAddress1", "PostalAddress2", "Eircode") if row.get(key, "").strip())
        return {
            "source_id": source_id,
            "name": name,
            "space_type": "library",
            "location": source_point(row["Longitude"], row["Latitude"]),
            "location_method": "source_point",
            "address": address,
            "description": row.get("CultureDescription", ""),
            "source_attributes": row,
            **dict.fromkeys(FACILITY_FIELDS),
        }, []
