"""Shared snapshot validation and transactional source-key upserts."""
import hashlib
import json
from collections import Counter
from pathlib import Path

from django.contrib.gis.gdal import GDALException
from django.contrib.gis.geos import GEOSException, Point
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from spaces.models import AdministrativeArea, FACILITY_FIELDS


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise CommandError(f"Cannot read JSON file {path}: {exc}") from exc


def load_identities(path):
    mapping = read_json(path)
    if not isinstance(mapping, dict):
        raise CommandError("Identity mapping must be an object of stable IDs and name aliases.")
    aliases = {}
    for stable_id, names in mapping.items():
        if not stable_id or not isinstance(names, list) or not names:
            raise CommandError("Each stable ID needs a non-empty list of name aliases.")
        for name in names:
            if not isinstance(name, str) or not name.strip():
                raise CommandError("Identity aliases must be non-empty strings.")
            key = name.strip().casefold()
            if key in aliases:
                raise CommandError(f"Ambiguous identity alias: {name}")
            aliases[key] = stable_id
    return aliases


def source_point(longitude, latitude):
    # GeoDjango point order is longitude, latitude; values remain EPSG:4326.
    if isinstance(longitude, bool) or isinstance(latitude, bool):
        raise ValueError("Boolean coordinates are invalid.")
    if longitude is None or latitude is None or longitude == "" or latitude == "":
        raise ValueError("Missing coordinates.")
    return Point(float(longitude), float(latitude), srid=4326)


class SnapshotImportCommand(BaseCommand):
    dataset = None
    model = None
    source_kind = None
    uses_study_area = False

    def add_arguments(self, parser):
        parser.add_argument("--manifest", default="data/source-manifest.json")
        parser.add_argument("--dry-run", action="store_true", help="Validate and roll back all writes.")

    def load_snapshot(self, manifest_path):
        manifest_path = Path(manifest_path)
        manifest = read_json(manifest_path)
        try:
            entry = manifest[self.dataset]
            path = manifest_path.parent / entry["file"]
            retrieved = parse_datetime(entry["retrieved_at"])
            expected_hash = entry["sha256"]
            if not retrieved or not timezone.is_aware(retrieved):
                raise ValueError("retrieved_at must be an ISO timestamp with a timezone.")
            if not isinstance(expected_hash, str) or len(expected_hash) != 64:
                raise ValueError("sha256 must contain 64 hexadecimal characters.")
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash.lower():
                raise ValueError("Snapshot checksum does not match the manifest.")
            for field in ("source_url", "licence"):
                if not isinstance(entry[field], str) or not entry[field].strip():
                    raise ValueError(f"Missing {field}.")
            if type(entry["source_srid"]) is not int or entry["source_srid"] <= 0:
                raise ValueError("source_srid must be an explicit positive EPSG code.")
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise CommandError(f"Invalid {self.dataset} manifest entry: {exc}") from exc
        metadata = {
            "source_kind": self.source_kind,
            "source_url": entry["source_url"],
            "source_licence": entry["licence"],
            "source_retrieved_at": retrieved,
            "source_srid": entry["source_srid"],
        }
        self.entry = entry
        self.manifest = manifest
        self.manifest_directory = manifest_path.parent
        return path, metadata

    def handle(self, *args, **options):
        self.options = options
        path, metadata = self.load_snapshot(options["manifest"])
        records = self.load_records(path)
        if self.uses_study_area:
            try:
                area_entry = self.manifest["dcc-administrative-areas"]
                required_ids = set(load_identities(
                    self.manifest_directory / area_entry["identity_map"],
                ).values())
            except (KeyError, TypeError) as exc:
                raise CommandError("The manifest needs a DCC area identity mapping.") from exc
            imported_ids = set(AdministrativeArea.objects.filter(
                source_dataset="dcc-administrative-areas",
            ).values_list("source_id", flat=True))
            missing = required_ids - imported_ids
            if not required_ids or missing:
                raise CommandError(
                    "Import DCC administrative areas completely before importing locations. "
                    f"Missing IDs: {sorted(missing)}"
                )
        counts = Counter()
        seen = {}
        with transaction.atomic():
            for number, row in enumerate(records, 1):
                counts["read"] += 1
                try:
                    if not isinstance(row, dict):
                        raise ValueError("Each record must be an object.")
                    defaults, issues = self.parse_record(row)
                    source_id = defaults.pop("source_id")
                    defaults = {**metadata, **defaults}
                    candidate = self.model(
                        source_dataset=self.dataset, source_id=source_id, **defaults,
                    )
                    candidate.full_clean(validate_unique=False, validate_constraints=False)
                except (KeyError, TypeError, ValueError, ValidationError, GEOSException, GDALException) as exc:
                    counts["rejected"] += 1
                    self.stderr.write(f"Rejected row {number}: {exc}")
                    continue

                if source_id in seen:
                    if seen[source_id] != defaults:
                        raise CommandError(f"Conflicting duplicate source ID {source_id}; all writes rolled back.")
                    counts["duplicate"] += 1
                    continue
                seen[source_id] = defaults
                for issue in issues:
                    counts["warnings"] += 1
                    self.stderr.write(f"{source_id}: {issue}")

                if self.uses_study_area and not AdministrativeArea.objects.filter(
                    source_dataset="dcc-administrative-areas",
                    boundary__covers=candidate.location,
                ).exists():
                    counts["outside"] += 1
                    self.stderr.write(f"Outside DCC study area: {source_id}")
                    continue

                existing = self.model.objects.filter(
                    source_dataset=self.dataset, source_id=source_id,
                ).first()
                if existing is None:
                    candidate.imported_at = timezone.now()
                    candidate.save()
                    counts["created"] += 1
                else:
                    if getattr(existing, "facility_import_locked", False):
                        defaults = {k: v for k, v in defaults.items() if k not in FACILITY_FIELDS}
                    changes = {k: v for k, v in defaults.items() if getattr(existing, k) != v}
                    if changes:
                        for field, value in changes.items():
                            setattr(existing, field, value)
                        existing.imported_at = timezone.now()
                        existing.save(update_fields=[*changes, "imported_at"])
                        counts["updated"] += 1
                    else:
                        counts["unchanged"] += 1
            if options["dry_run"]:
                transaction.set_rollback(True)
        label = "DRY RUN (rolled back)" if options["dry_run"] else self.dataset
        self.stdout.write(label + ": " + ", ".join(
            f"{key}={counts[key]}" for key in
            ("read", "created", "updated", "unchanged", "duplicate", "outside", "rejected", "warnings")
        ))
        self.report_duplicates()

    def report_duplicates(self):
        # Same names can identify different branches; report rather than auto-merge.
        if self.uses_study_area:
            from django.db.models import Count
            from django.db.models.functions import Lower

            candidates = self.model.objects.filter(source_dataset=self.dataset).order_by().annotate(
                folded_name=Lower("name"),
            ).values("folded_name").annotate(total=Count("pk")).filter(total__gt=1)
            for candidate in candidates:
                self.stderr.write(
                    f"Review possible duplicate/shared name: {candidate['folded_name']!r} "
                    f"({candidate['total']} records; not merged)"
                )
