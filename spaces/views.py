from django.shortcuts import render
from rest_framework import status, viewsets
from rest_framework.exceptions import APIException, ValidationError

from .models import FACILITY_FIELDS, StudySpace
from .serializers import StudySpaceSerializer

# "unknown" matches SQL NULL, so unknown facilities are never treated as true or false.
FACILITY_FILTER_VALUES = {"true": True, "false": False, "unknown": None}


def home(request):
    return render(request, "spaces/home.html")


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
        if self.action == "list":
            queryset = filter_study_spaces(queryset, self.request.query_params)
        return queryset

    def perform_destroy(self, instance):
        if instance.is_imported:
            raise ImportedRecordConflict()
        instance.delete()
