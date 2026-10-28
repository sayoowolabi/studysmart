from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.test import RequestFactory
from django.urls import reverse
from types import SimpleNamespace

from spaces.admin import StudySpaceAdmin
from spaces.models import AdministrativeArea, FACILITY_FIELDS, StudySpace


def make_space(**overrides):
    values = {
        "name": "Fictional Test Space", "space_type": "cafe",
        "location": Point(-6.26, 53.35, srid=4326),
    }
    values.update(overrides)
    return StudySpace(**values)


class StudySpaceModelTests(TestCase):
    def test_both_categories_and_three_facility_states(self):
        for category in ("library", "cafe"):
            for value in (True, False, None):
                space = make_space(space_type=category, **dict.fromkeys(FACILITY_FIELDS, value))
                space.full_clean()
                space.save()
                space.refresh_from_db()
                for field in FACILITY_FIELDS:
                    self.assertIs(getattr(space, field), value)

    def test_bad_required_values_and_coordinates(self):
        for overrides in (
            {"name": " "}, {"space_type": "university"}, {"location": None},
            {"source_id": ""}, {"source_dataset": ""},
            {"location": Point(181, 53, srid=4326)},
            {"location": Point(-6, 91, srid=4326)},
            {"location": Point(float("inf"), 53, srid=4326)},
            {"location": Point(float("nan"), 53, srid=4326)},
            {"location": Point(-6, 53, 2, srid=4326)},
            {"source_attributes": []},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                make_space(**overrides).full_clean()

    def test_database_constraints_prevent_duplicate_sources_and_invalid_types(self):
        make_space(source_dataset="fixture", source_id="1").save()
        for values in (
            {"source_dataset": "fixture", "source_id": "1"},
            {"space_type": "invalid"},
        ):
            with self.subTest(values=values), transaction.atomic(), self.assertRaises(IntegrityError):
                make_space(**values).save()

    def test_source_namespaces_and_osm_element_types_do_not_collide(self):
        for dataset, source_id in (("osm-cafes", "node/1"), ("osm-cafes", "way/1"), ("manual", "node/1")):
            make_space(source_dataset=dataset, source_id=source_id).save()
        self.assertEqual(StudySpace.objects.count(), 3)

    def test_locked_facilities_require_evidence_notes(self):
        with self.assertRaises(ValidationError):
            make_space(facility_import_locked=True).full_clean()

    def test_indoor_cafe_filter_can_be_empty_without_removing_unknown_cafes(self):
        make_space(space_type="cafe", indoor_seating=None).save()
        make_space(space_type="library", indoor_seating=True).save()
        self.assertFalse(StudySpace.objects.filter(space_type="cafe", indoor_seating=True).exists())
        self.assertEqual(StudySpace.objects.count(), 2)


class AreaModelTests(TestCase):
    def test_polygon_model_validation(self):
        valid = Polygon.from_bbox((-6.4, 53.25, -6.1, 53.45))
        valid.srid = 4326
        area = AdministrativeArea(name="Fictional Area", boundary=MultiPolygon(valid, srid=4326))
        area.full_clean()
        area.save()
        area.refresh_from_db()
        self.assertTrue(area.boundary.valid)
        self.assertEqual(area.boundary.srid, 4326)

    def test_invalid_and_empty_boundaries_are_rejected(self):
        bowtie = Polygon(((-6.4, 53.2), (-6.1, 53.4), (-6.4, 53.4), (-6.1, 53.2), (-6.4, 53.2)))
        for boundary in (MultiPolygon(bowtie, srid=4326), MultiPolygon(srid=4326)):
            with self.subTest(boundary=boundary), self.assertRaises(ValidationError):
                AdministrativeArea(name="Fictional Area", boundary=boundary).full_clean()


class AdminTests(TestCase):
    def test_admin_form_protects_edits_and_requires_notes(self):
        space = make_space()
        space.save()
        user = get_user_model().objects.create_superuser(username="fixture-admin")
        request = RequestFactory().get("/admin/")
        request.user = user
        admin = StudySpaceAdmin(StudySpace, AdminSite())
        form_class = admin.get_form(request, obj=space)
        data = {
            "name": space.name, "space_type": "cafe", "location": space.location.ewkt,
            **dict.fromkeys(FACILITY_FIELDS, "unknown"),
            "indoor_seating": "true", "facility_verification_notes": "Fictional test evidence.",
        }
        form = form_class(data=data, instance=space)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.cleaned_data["facility_import_locked"])
        admin.save_model(request, form.save(commit=False), form, True)
        space.refresh_from_db()
        self.assertIs(space.indoor_seating, True)
        self.assertTrue(space.facility_import_locked)
        data["facility_verification_notes"] = ""
        data["facility_import_locked"] = "on"
        self.assertFalse(form_class(data=data, instance=space).is_valid())

    def test_editing_facilities_sets_lock_and_verification_time(self):
        space = make_space(facility_verification_notes="Synthetic test evidence; not a real venue.")
        admin = StudySpaceAdmin(StudySpace, AdminSite())
        admin.save_model(None, space, SimpleNamespace(changed_data=["indoor_seating"]), False)
        space.refresh_from_db()
        self.assertTrue(space.facility_import_locked)
        self.assertIsNotNone(space.facility_verified_at)
        for field in ("source_id", "source_attributes", "source_retrieved_at"):
            self.assertIn(field, admin.get_readonly_fields(None))

    def test_import_owned_fields_are_read_only_for_imported_records(self):
        admin = StudySpaceAdmin(StudySpace, AdminSite())
        imported = make_space(source_dataset="osm-cafes", source_id="node/1", source_kind="osm")
        for field in ("name", "space_type", "location", "address", "description"):
            self.assertIn(field, admin.get_readonly_fields(None, imported))
            self.assertNotIn(field, admin.get_readonly_fields(None, make_space()))
        self.assertNotIn("indoor_seating", admin.get_readonly_fields(None, imported))

    def test_admin_pages_require_login_and_model_permissions(self):
        url = reverse("admin:spaces_studyspace_changelist")
        self.assertEqual(self.client.get(url).status_code, 302)
        user = get_user_model().objects.create_user(username="fixture-staff", is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get(url).status_code, 403)
