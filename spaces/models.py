import uuid

from django.contrib.gis.db import models
from django.core.exceptions import ValidationError

from .validators import validate_boundary, validate_point

FACILITY_FIELDS = (
    "indoor_seating", "outdoor_seating", "has_wifi", "has_outlets", "laptop_allowed",
)


class SourceRecord(models.Model):
    class SourceKind(models.TextChoices):
        OFFICIAL = "official", "Official dataset"
        OSM = "osm", "OpenStreetMap"
        MANUAL = "manual", "Manual record"
        DEMO = "demo", "Demonstration data"

    source_dataset = models.CharField(max_length=100, default="manual")
    source_id = models.CharField(max_length=255, default=uuid.uuid4)
    source_kind = models.CharField(max_length=10, choices=SourceKind, default=SourceKind.MANUAL)
    source_url = models.URLField(max_length=2048, blank=True)
    source_licence = models.CharField(max_length=255, blank=True)
    source_retrieved_at = models.DateTimeField(null=True, blank=True)
    source_srid = models.PositiveIntegerField(default=4326)
    source_attributes = models.JSONField(default=dict, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        errors = {}
        for field in ("name", "source_dataset", "source_id"):
            if not str(getattr(self, field) or "").strip():
                errors[field] = "This value must not be blank."
        if not isinstance(self.source_attributes, dict):
            errors["source_attributes"] = "Source attributes must be a JSON object."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.name


class StudySpace(SourceRecord):
    class SpaceType(models.TextChoices):
        LIBRARY = "library", "Library"
        CAFE = "cafe", "Café"

    class LocationMethod(models.TextChoices):
        SOURCE_POINT = "source_point", "Source coordinates"
        OSM_CENTER = "osm_center", "Approximate Overpass centre"
        MANUAL = "manual", "Manually supplied point"

    name = models.CharField(max_length=255)
    space_type = models.CharField(max_length=10, choices=SpaceType, db_index=True)
    location = models.PointField(srid=4326, spatial_index=True, validators=[validate_point])
    location_method = models.CharField(
        max_length=20, choices=LocationMethod, default=LocationMethod.MANUAL,
    )
    address = models.TextField(blank=True)
    description = models.TextField(blank=True)
    indoor_seating = models.BooleanField(null=True, blank=True, default=None)
    outdoor_seating = models.BooleanField(null=True, blank=True, default=None)
    has_wifi = models.BooleanField(null=True, blank=True, default=None)
    has_outlets = models.BooleanField(null=True, blank=True, default=None)
    laptop_allowed = models.BooleanField(null=True, blank=True, default=None)
    facility_import_locked = models.BooleanField(
        default=False,
        help_text="Protect all five facility values from imports. Admin facility edits enable this.",
    )
    facility_verification_notes = models.TextField(blank=True)
    facility_verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_dataset", "source_id"], name="unique_study_space_source",
            ),
            models.CheckConstraint(
                condition=models.Q(space_type__in=["library", "cafe"]),
                name="valid_study_space_type",
            ),
        ]

    @property
    def is_imported(self):
        # Import commands own these records and recreate or overwrite them on re-import.
        return self.source_kind in {self.SourceKind.OFFICIAL, self.SourceKind.OSM}

    def clean(self):
        super().clean()
        if self.facility_import_locked and not self.facility_verification_notes.strip():
            raise ValidationError({
                "facility_verification_notes": "Explain the evidence for protected facility values.",
            })


class AdministrativeArea(SourceRecord):
    name = models.CharField(max_length=255)
    boundary = models.MultiPolygonField(
        srid=4326, spatial_index=True, validators=[validate_boundary],
    )

    class Meta:
        ordering = ["name", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_dataset", "source_id"], name="unique_administrative_area_source",
            ),
        ]
