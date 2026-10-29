from django.db import DatabaseError
from django.db.models import Count, Q
from django.shortcuts import render
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import FACILITY_FIELDS, StudySpace
from .serializers import (
    NearbyQuerySerializer, PointQuerySerializer, StudySpaceDistanceSerializer,
    StudySpaceSerializer,
)
from .spatial import (
    area_boundaries, area_coverage, nearest_space, search_point, spaces_within,
)

# "unknown" matches SQL NULL, so unknown facilities are never treated as true or false.
FACILITY_FILTER_VALUES = {"true": True, "false": False, "unknown": None}


# Facility filters offered on the map page, in display order.
MAP_FACILITY_FILTERS = (
    ("indoor_seating", "Indoor seating"),
    ("has_wifi", "Wi-Fi"),
    ("has_outlets", "Power outlets"),
)


def confirmed_facility_counts():
    """Records confirming each map facility (value true), or None if the database is unavailable."""
    try:
        return StudySpace.objects.aggregate(**{
            field: Count("pk", filter=Q(**{field: True})) for field, _ in MAP_FACILITY_FILTERS
        })
    except DatabaseError:
        return None


def home(request):
    # A filter with no confirmed records could only ever return nothing, so the template
    # disables it. It becomes available on the next page load once confirmed data exists.
    counts = confirmed_facility_counts()
    facility_filters = [
        {"field": field, "label": label, "confirmed": None if counts is None else counts[field]}
        for field, label in MAP_FACILITY_FILTERS
    ]
    return render(request, "spaces/home.html", {"facility_filters": facility_filters})


class ImportedRecordConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = (
        "Imported records cannot be deleted because the next import would recreate them. "
        "Only manually created records can be deleted."
    )
    default_code = "imported_record"


def filter_study_spaces(queryset, params):
    """Apply ?type= and tri-state facility filters, rejecting unrecognised values."""
    space_type = params.get("type")
    if space_type is not None:
        if space_type not in StudySpace.SpaceType.values:
            raise ValidationError({"type": [f"Use one of: {', '.join(StudySpace.SpaceType.values)}."]})
        queryset = queryset.filter(space_type=space_type)

    for field in FACILITY_FIELDS:
        value = params.get(field)
        if value is None:
            continue
        if value.lower() not in FACILITY_FILTER_VALUES:
            raise ValidationError({field: ["Use true, false or unknown."]})
        expected = FACILITY_FILTER_VALUES[value.lower()]
        if expected is None:
            queryset = queryset.filter(**{f"{field}__isnull": True})
        else:
            queryset = queryset.filter(**{field: expected})
    return queryset


class StudySpaceViewSet(viewsets.ModelViewSet):
    """Public read access; writes need the matching Django model permission."""

    queryset = StudySpace.objects.all()
    serializer_class = StudySpaceSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action in {"list", "nearby", "nearest"}:
            queryset = filter_study_spaces(queryset, self.request.query_params)
        return queryset

    def perform_destroy(self, instance):
        if instance.is_imported:
            raise ImportedRecordConflict()
        instance.delete()

    def validated_query(self, serializer_class):
        query = serializer_class(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        return query.validated_data

    @action(detail=False)
    def nearby(self, request):
        """GET /api/spaces/nearby/?lat=&lng=&radius= (metres), nearest first."""
        query = self.validated_query(NearbyQuerySerializer)
        point = search_point(query["lat"], query["lng"])
        spaces = spaces_within(self.get_queryset(), point, query["radius"])
        return Response(StudySpaceDistanceSerializer(spaces, many=True).data)

    @action(detail=False)
    def nearest(self, request):
        """GET /api/spaces/nearest/?lat=&lng= for the closest space matching the filters."""
        query = self.validated_query(PointQuerySerializer)
        space = nearest_space(self.get_queryset(), search_point(query["lat"], query["lng"]))
        if space is None:
            raise NotFound("No study space matches these filters.")
        return Response(StudySpaceDistanceSerializer(space).data)


class AreaCoverageView(APIView):
    """GET /api/areas/coverage/: library and café counts per administrative area."""

    # Set explicitly: the default model-permission class needs a queryset. GET is the only method.
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(area_coverage())


class AreaBoundaryView(APIView):
    """GET /api/areas/: administrative-area outlines as GeoJSON for the map overlay."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response(area_boundaries())
