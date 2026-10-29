"""REST API tests use fictional records and a separate PostGIS test database."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from spaces.models import FACILITY_FIELDS, StudySpace

LIST_URL = reverse("spaces:studyspace-list")


def detail_url(space):
    return reverse("spaces:studyspace-detail", args=[space.pk])


def make_space(**overrides):
    values = {
        "name": "Fictional Test Space", "space_type": "cafe",
        "location": Point(-6.26, 53.35, srid=4326),
    }
    values.update(overrides)
    return StudySpace.objects.create(**values)


def make_imported_cafe():
    return make_space(
        name="Fictional Imported Cafe", source_dataset="osm-cafes",
        source_id="node/1", source_kind="osm",
    )


def valid_payload(**overrides):
    payload = {
        "name": "Fictional New Library", "space_type": "library",
        "latitude": 53.34, "longitude": -6.27,
    }
    payload.update(overrides)
    return payload


class APITestBase(APITestCase):
    def login_with_permissions(self, *codenames):
        user = get_user_model().objects.create_user(username="fixture-editor")
        user.user_permissions.set(Permission.objects.filter(codename__in=codenames))
        self.client.force_login(user)
        return user

    def login_as_editor(self):
        return self.login_with_permissions(
            "add_studyspace", "change_studyspace", "delete_studyspace",
        )


class ReadTests(APITestBase):
    def test_anonymous_list_detail_and_missing_record(self):
        space = make_space()
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(self.client.get(detail_url(space)).status_code, 200)
        missing = reverse("spaces:studyspace-detail", args=[999999])
        self.assertEqual(self.client.get(missing).status_code, 404)

    def test_coordinates_are_latitude_longitude_not_swapped(self):
        data = self.client.get(detail_url(make_space())).data
        self.assertAlmostEqual(data["latitude"], 53.35)
        self.assertAlmostEqual(data["longitude"], -6.26)

    def test_unknown_facilities_are_returned_as_null(self):
        data = self.client.get(detail_url(make_space())).data
        for field in FACILITY_FIELDS:
            self.assertIsNone(data[field])


class FilterTests(APITestBase):
    def setUp(self):
        make_space(name="Seated Cafe", indoor_seating=True)
        make_space(name="Standing Cafe", indoor_seating=False)
        make_space(name="Unknown Cafe", indoor_seating=None)
        make_space(name="Seated Library", space_type="library", indoor_seating=True)

    def list_names(self, query):
        response = self.client.get(LIST_URL + query)
        self.assertEqual(response.status_code, 200, response.data)
        return sorted(item["name"] for item in response.data)

    def test_type_filter(self):
        self.assertEqual(self.list_names("?type=library"), ["Seated Library"])

    def test_confirmed_indoor_seating_excludes_false_and_unknown(self):
        self.assertEqual(self.list_names("?type=cafe&indoor_seating=true"), ["Seated Cafe"])

    def test_unknown_filter_matches_only_null_values(self):
        self.assertEqual(self.list_names("?indoor_seating=unknown"), ["Unknown Cafe"])

    def test_false_filter_matches_only_confirmed_absence(self):
        self.assertEqual(self.list_names("?indoor_seating=false"), ["Standing Cafe"])

    def test_invalid_filter_values_are_rejected(self):
        for query in ("?type=university", "?indoor_seating=maybe"):
            with self.subTest(query=query):
                self.assertEqual(self.client.get(LIST_URL + query).status_code, 400)


class PermissionTests(APITestBase):
    def test_anonymous_users_cannot_modify(self):
        space = make_space()
        self.assertEqual(self.client.post(LIST_URL, valid_payload(), format="json").status_code, 403)
        self.assertEqual(self.client.patch(detail_url(space), {"name": "X"}, format="json").status_code, 403)
        self.assertEqual(self.client.delete(detail_url(space)).status_code, 403)
        space.refresh_from_db()
        self.assertEqual(space.name, "Fictional Test Space")

    def test_logged_in_user_without_model_permissions_cannot_write(self):
        self.login_with_permissions()
        self.assertEqual(self.client.post(LIST_URL, valid_payload(), format="json").status_code, 403)

    def test_session_writes_require_csrf_token(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.login_as_editor())
        self.assertEqual(client.post(LIST_URL, valid_payload(), format="json").status_code, 403)
        self.assertFalse(StudySpace.objects.exists())


class WriteTests(APITestBase):
    def setUp(self):
        self.login_as_editor()

    def test_valid_create_is_a_manual_record(self):
        response = self.client.post(LIST_URL, valid_payload(), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        space = StudySpace.objects.get(pk=response.data["id"])
        self.assertEqual((space.location.x, space.location.y), (-6.27, 53.34))
        self.assertEqual(space.source_kind, "manual")

    def test_missing_required_fields(self):
        response = self.client.post(LIST_URL, {}, format="json")
        self.assertEqual(response.status_code, 400)
        for field in ("name", "space_type", "latitude", "longitude"):
            self.assertIn(field, response.data)

    def test_invalid_coordinates_are_rejected(self):
        for overrides in (
            {"latitude": 91}, {"longitude": -180.5}, {"longitude": "west"},
            {"latitude": "NaN"}, {"longitude": "Infinity"},
        ):
            with self.subTest(overrides=overrides):
                response = self.client.post(LIST_URL, valid_payload(**overrides), format="json")
                self.assertEqual(response.status_code, 400)
        self.assertFalse(StudySpace.objects.exists())

    def test_facility_correction_requires_notes_and_locks_imports(self):
        space = make_imported_cafe()
        response = self.client.patch(detail_url(space), {"has_wifi": True}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("facility_verification_notes", response.data)

        response = self.client.patch(detail_url(space), {
            "has_wifi": True, "facility_verification_notes": "Fictional site visit.",
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        space.refresh_from_db()
        self.assertIs(space.has_wifi, True)
        self.assertTrue(space.facility_import_locked)

    def test_source_owned_fields_of_imported_records_are_rejected(self):
        space = make_imported_cafe()
        response = self.client.patch(detail_url(space), {"name": "Renamed"}, format="json")
        self.assertEqual(response.status_code, 400)
        space.refresh_from_db()
        self.assertEqual(space.name, "Fictional Imported Cafe")

    def test_delete_manual_record_but_not_imported_record(self):
        manual, imported = make_space(), make_imported_cafe()
        self.assertEqual(self.client.delete(detail_url(manual)).status_code, 204)
        self.assertEqual(self.client.delete(detail_url(imported)).status_code, 409)
        self.assertEqual(list(StudySpace.objects.all()), [imported])
