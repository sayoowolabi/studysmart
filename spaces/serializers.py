"""JSON representation and validation of study spaces for the REST API."""
import copy
import math

from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers

from .models import FACILITY_FIELDS, SOURCE_OWNED_FIELDS, StudySpace


class StudySpaceSerializer(serializers.ModelSerializer):
    # Exposed as plain numbers; validate() combines them into one EPSG:4326 Point.
    latitude = serializers.FloatField(source="location.y", min_value=-90, max_value=90)
    longitude = serializers.FloatField(source="location.x", min_value=-180, max_value=180)

    class Meta:
        model = StudySpace
        fields = [
            "id", "name", "space_type", "latitude", "longitude", "location_method",
            "address", "description", *FACILITY_FIELDS,
            "facility_import_locked", "facility_verification_notes", "facility_verified_at",
            "source_dataset", "source_id", "source_kind", "source_url", "source_licence",
            "source_retrieved_at", "imported_at",
        ]
        read_only_fields = [
            "location_method", "facility_import_locked", "facility_verified_at",
            "source_dataset", "source_id", "source_kind", "source_url", "source_licence",
            "source_retrieved_at", "imported_at",
        ]

    def validate(self, attrs):
        if "location" in attrs:
            attrs["location"] = self.build_point(attrs["location"])
        if self.instance is not None and self.instance.is_imported:
            self.reject_source_owned_changes(attrs)
        self.lock_changed_facilities(attrs)

        # Reuse the model's own rules (point validator, blank checks, lock notes).
        candidate = copy.copy(self.instance) if self.instance else StudySpace()
        for field, value in attrs.items():
            setattr(candidate, field, value)
        try:
            candidate.full_clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(serializers.as_serializer_error(exc))
        return attrs

    def build_point(self, coordinates):
        # A PATCH may send only one coordinate; keep the other from the stored point.
        current = self.instance.location if self.instance else None
        longitude = coordinates.get("x", current.x if current else None)
        latitude = coordinates.get("y", current.y if current else None)
        return Point(longitude, latitude, srid=4326)

    def reject_source_owned_changes(self, attrs):
        errors = {
            field: (
                f"This value comes from {self.instance.source_dataset} and would be "
                "overwritten by the next import."
            )
            for field in SOURCE_OWNED_FIELDS
            if field in attrs and attrs[field] != getattr(self.instance, field)
        }
        if errors:
            raise serializers.ValidationError(errors)

    def lock_changed_facilities(self, attrs):
        # Mirrors the admin: any facility change protects all five values from imports.
        changed = [
            field for field in FACILITY_FIELDS
            if field in attrs and attrs[field] != getattr(self.instance, field, None)
        ]
        if changed:
            attrs["facility_import_locked"] = True
            attrs["facility_verified_at"] = timezone.now()


class StudySpaceDistanceSerializer(StudySpaceSerializer):
    """A study space plus its distance from the search point, from the distance annotation."""

    distance_m = serializers.SerializerMethodField()

    class Meta(StudySpaceSerializer.Meta):
        fields = [*StudySpaceSerializer.Meta.fields, "distance_m"]

    def get_distance_m(self, space):
        return round(space.distance.m, 1)


MAX_SEARCH_RADIUS_M = 10_000


def require_finite(value):
    # NaN passes min/max comparisons, so it must be rejected explicitly.
    if not math.isfinite(value):
        raise serializers.ValidationError("Must be a finite number.")


class PointQuerySerializer(serializers.Serializer):
    """Validates the ?lat=&lng= query parameters of a spatial search."""

    lat = serializers.FloatField(min_value=-90, max_value=90, validators=[require_finite])
    lng = serializers.FloatField(min_value=-180, max_value=180, validators=[require_finite])


class NearbyQuerySerializer(PointQuerySerializer):
    radius = serializers.FloatField(max_value=MAX_SEARCH_RADIUS_M, validators=[require_finite])

    def validate_radius(self, value):
        if value <= 0:
            raise serializers.ValidationError("Must be greater than 0 metres.")
        return value
