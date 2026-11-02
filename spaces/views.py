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
    StudySpaceNearestSerializer, StudySpaceSerializer,
)
from .spatial import (
    area_boundaries, area_coverage, areas_around, nearest_space, search_point, spaces_within,
)
from .universities import CAMPUSES

# "unknown" matches SQL NULL, so unknown facilities are never treated as true or false.
FACILITY_FILTER_VALUES = {"true": True, "false": False, "unknown": None}


# Search radii offered on the map page (metres); tests check they are within the API's limit.
RADIUS_CHOICES_M = (500, 1000, 2000, 5000)

# How many nearest results the map page lists; the first is selected by default.
RESULT_SIZE_CHOICES = (10, 25, 50)

# Facility filters offered on the map page, in display order. Power outlets and laptop
# permission remain API filters but are not offered here: almost no source records them.
MAP_FACILITY_FILTERS = (
    ("indoor_seating", "Indoor seating"),
    ("has_wifi", "Wi-Fi"),
)


def confirmed_facility_counts():
    """Cafés confirming each map facility (value true), or None if the database is unavailable."""
    try:
        return StudySpace.objects.filter(space_type=StudySpace.SpaceType.CAFE).aggregate(**{
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
    return render(request, "spaces/home.html", {
        "facility_filters": facility_filters,
        "campuses": CAMPUSES,
        "radius_choices": RADIUS_CHOICES_M,
        "result_size_choices": RESULT_SIZE_CHOICES,
    })


def about(request):
    """A short page explaining what StudySmart is for and how to use the map."""
    return render(request, "spaces/about.html", {
        "radius_choices": RADIUS_CHOICES_M,
        "result_size_choices": RESULT_SIZE_CHOICES,
    })


class ImportedRecordConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = (
        "Imported records cannot be deleted because the next import would recreate them. "
        "Only manually created records can be deleted."
    )
    default_code = "imported_record"


def valid_space_type(params, name):
    value = params.get(name)
    if value is not None and value not in StudySpace.SpaceType.values:
        raise ValidationError({name: [f"Use one of: {', '.join(StudySpace.SpaceType.values)}."]})
    return value


def filter_study_spaces(queryset, params):
    """
    Apply ?type= and tri-state facility filters, rejecting unrecognised values.
    ?facilities_apply_to=<type> limits the facility filters to that type; other types
    are returned whatever their facilities (the map page uses this for cafés).
    """
    space_type = valid_space_type(params, "type")
    if space_type is not None:
        queryset = queryset.filter(space_type=space_type)
    facilities_apply_to = valid_space_type(params, "facilities_apply_to")

    facility_filter = Q()
    for field in FACILITY_FIELDS:
        value = params.get(field)
        if value is None:
            continue
        if value.lower() not in FACILITY_FILTER_VALUES:
            raise ValidationError({field: ["Use true, false or unknown."]})
        expected = FACILITY_FILTER_VALUES[value.lower()]
        if expected is None:
            facility_filter &= Q(**{f"{field}__isnull": True})
        else:
            facility_filter &= Q(**{field: expected})

    # An empty Q() would turn "filter OR other types" into "other types only", so skip it.
    if facility_filter and facilities_apply_to is not None:
        facility_filter |= ~Q(space_type=facilities_apply_to)
    return queryset.filter(facility_filter)


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
        return Response(StudySpaceNearestSerializer(space).data)


class AreaCoverageView(APIView):
    """GET /api/areas/coverage/: library and café counts per administrative area."""

    # Set explicitly: the default model-permission class needs a queryset. GET is the only method.
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(area_coverage())


class AreaIntersectionView(APIView):
    """GET /api/areas/intersecting/?lat=&lng=&radius=: the areas around a search point."""

    permission_classes = [AllowAny]

    def get(self, request):
        query = NearbyQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        point = search_point(query.validated_data["lat"], query.validated_data["lng"])
        return Response(areas_around(point, query.validated_data["radius"]))


class AreaBoundaryView(APIView):
    """GET /api/areas/: administrative-area outlines as GeoJSON for the map overlay."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response(area_boundaries())
