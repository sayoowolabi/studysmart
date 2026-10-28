from django import forms
from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin
from django.utils import timezone

from .models import AdministrativeArea, FACILITY_FIELDS, StudySpace


class StudySpaceAdminForm(forms.ModelForm):
    class Meta:
        model = StudySpace
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        if any(field in self.changed_data for field in FACILITY_FIELDS):
            cleaned["facility_import_locked"] = True
        if cleaned.get("facility_import_locked") and not cleaned.get("facility_verification_notes", "").strip():
            self.add_error("facility_verification_notes", "Describe the evidence for the facility values.")
        return cleaned


SOURCE_READONLY = (
    "source_dataset", "source_id", "source_kind", "source_url", "source_licence",
    "source_retrieved_at", "source_srid", "source_attributes", "imported_at",
)


@admin.register(StudySpace)
class StudySpaceAdmin(GISModelAdmin):
    form = StudySpaceAdminForm
    list_display = ("name", "space_type", "indoor_seating", "has_wifi", "source_kind")
    list_filter = ("space_type", *FACILITY_FIELDS, "facility_import_locked", "source_kind")
    search_fields = ("name", "address", "source_id")
    readonly_fields = (*SOURCE_READONLY, "location_method", "facility_verified_at")

    def save_model(self, request, obj, form, change):
        facility_edits = any(field in form.changed_data for field in FACILITY_FIELDS)
        if facility_edits or (obj.facility_import_locked and "facility_import_locked" in form.changed_data):
            obj.facility_import_locked = True
            obj.facility_verified_at = timezone.now()
        elif not obj.facility_import_locked:
            obj.facility_verified_at = None
        super().save_model(request, obj, form, change)


@admin.register(AdministrativeArea)
class AdministrativeAreaAdmin(GISModelAdmin):
    list_display = ("name", "source_dataset", "source_id")
    search_fields = ("name", "source_id")
    readonly_fields = SOURCE_READONLY
