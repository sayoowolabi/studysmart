"""Geometry validation shared by model forms and import commands."""
import math

from django.core.exceptions import ValidationError


def validate_point(value):
    if value.empty or value.geom_type != "Point" or value.srid != 4326 or value.hasz:
        raise ValidationError("A non-empty two-dimensional point in EPSG:4326 is required.")
    if not all(math.isfinite(v) for v in (value.x, value.y)):
        raise ValidationError("Coordinates must be finite numbers.")
    if not (-180 <= value.x <= 180 and -90 <= value.y <= 90):
        raise ValidationError("Longitude or latitude is outside its valid range.")


def validate_boundary(value):
    if value.empty or value.geom_type != "MultiPolygon" or value.srid != 4326 or value.hasz:
        raise ValidationError("A non-empty two-dimensional multipolygon in EPSG:4326 is required.")
    if not value.valid:
        raise ValidationError("Boundary geometry must be valid.")
    xmin, ymin, xmax, ymax = value.extent
    if not all(math.isfinite(v) for v in value.extent):
        raise ValidationError("Boundary coordinates must be finite.")
    if not (-180 <= xmin <= xmax <= 180 and -90 <= ymin <= ymax <= 90):
        raise ValidationError("Boundary coordinates are outside longitude/latitude bounds.")
