"""Spatial queries for the API. All geometry work runs in PostGIS, not Python."""
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.db.models import Count, Subquery

from .models import AdministrativeArea, StudySpace


def search_point(latitude, longitude):
    # GeoDjango points are (x=longitude, y=latitude), in the same EPSG:4326 as stored data.
    return Point(longitude, latitude, srid=4326)


def with_distance(queryset, point):
    # For longitude/latitude geometry GeoDjango uses ST_DistanceSphere, which returns metres.
    # The same annotation is used to filter, sort and report, so the three always agree.
    return queryset.annotate(distance=Distance("location", point)).order_by("distance", "pk")


def spaces_within(queryset, point, radius_m):
    """Study spaces whose distance from the point is at most radius_m metres, nearest first."""
    return with_distance(queryset, point).filter(distance__lte=D(m=radius_m))


def nearest_space(queryset, point):
    """The single closest study space (SQL LIMIT 1), or None if nothing matches."""
    return with_distance(queryset, point).first()


def area_coverage():
    """Library and café counts inside each administrative area, ordered by area name."""
    coverage = []
    for area in AdministrativeArea.objects.values("id", "source_id", "name"):
        # A subquery keeps the large boundary polygon inside the database.
        boundary = AdministrativeArea.objects.filter(pk=area["id"]).values("boundary")
        # ST_CoveredBy includes points on an edge, so a point on a shared border counts in both
        # areas. order_by() clears the model's default ordering so rows group by type only.
        counts = dict(
            StudySpace.objects.filter(location__coveredby=Subquery(boundary))
            .order_by()
            .values_list("space_type")
            .annotate(count=Count("pk"))
        )
        coverage.append({
            **area,
            "library_count": counts.get(StudySpace.SpaceType.LIBRARY, 0),
            "cafe_count": counts.get(StudySpace.SpaceType.CAFE, 0),
            "total_count": sum(counts.values()),
        })
    return coverage
