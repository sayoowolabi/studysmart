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

    def test_each_operation_needs_its_own_model_permission(self):
        self.login_with_permissions("add_studyspace")
        response = self.client.post(LIST_URL, valid_payload(), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        space = StudySpace.objects.get(pk=response.data["id"])
        self.assertEqual(self.client.patch(detail_url(space), {"name": "X"}, format="json").status_code, 403)
        self.assertEqual(self.client.delete(detail_url(space)).status_code, 403)
        space.refresh_from_db()
        self.assertEqual(space.name, "Fictional New Library")

    def test_no_api_endpoint_accepts_anonymous_writes(self):
        space = make_space()
        urls = [
            LIST_URL, detail_url(space),
            reverse("spaces:studyspace-nearby"), reverse("spaces:studyspace-nearest"),
            reverse("spaces:area-list"), reverse("spaces:area-coverage"),
        ]
        for url in urls:
            for method in ("post", "put", "patch", "delete"):
                with self.subTest(url=url, method=method):
                    response = getattr(self.client, method)(url, valid_payload(), format="json")
                    # 403: authentication required; 405: the endpoint is read-only.
                    self.assertIn(response.status_code, (403, 405))
        self.assertEqual(list(StudySpace.objects.values_list("name", flat=True)), ["Fictional Test Space"])


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

    def test_invalid_type_and_facility_values_are_rejected(self):
        for overrides, field in (
            ({"space_type": "university"}, "space_type"),
            ({"has_wifi": "maybe"}, "has_wifi"),
            ({"indoor_seating": 2}, "indoor_seating"),
        ):
            with self.subTest(overrides=overrides):
                response = self.client.post(LIST_URL, valid_payload(**overrides), format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.data)
        self.assertFalse(StudySpace.objects.exists())

    def test_null_facility_is_stored_as_unknown(self):
        response = self.client.post(LIST_URL, valid_payload(indoor_seating=None), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        space = StudySpace.objects.get()
        self.assertIsNone(space.indoor_seating)
        self.assertFalse(space.facility_import_locked)

    def test_read_only_provenance_fields_cannot_be_spoofed(self):
        # Claiming to be an imported OSM record would make the record undeletable.
        response = self.client.post(LIST_URL, valid_payload(
            source_kind="osm", source_dataset="osm-cafes", source_id="node/1",
            facility_import_locked=True, facility_verified_at="2020-01-01T00:00:00Z",
            imported_at="2020-01-01T00:00:00Z",
        ), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        space = StudySpace.objects.get()
        self.assertEqual((space.source_kind, space.source_dataset), ("manual", "manual"))
        self.assertNotEqual(space.source_id, "node/1")
        self.assertFalse(space.facility_import_locked)
        self.assertIsNone(space.facility_verified_at)
        self.assertIsNone(space.imported_at)
        self.assertEqual(self.client.delete(detail_url(space)).status_code, 204)

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


class UpdateTests(APITestBase):
    def setUp(self):
        self.login_as_editor()
        self.space = make_space()

    def test_patch_updates_manual_record_and_keeps_the_other_coordinate(self):
        response = self.client.patch(
            detail_url(self.space), {"name": "Renamed Space", "latitude": 53.36}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.space.refresh_from_db()
        self.assertEqual(self.space.name, "Renamed Space")
        self.assertEqual((self.space.location.x, self.space.location.y), (-6.26, 53.36))

    def test_invalid_patch_is_rejected_without_changes(self):
        for payload in (
            {"latitude": 91}, {"longitude": "east"}, {"space_type": "university"},
            {"name": " "}, {"has_wifi": "maybe"},
        ):
            with self.subTest(payload=payload):
                response = self.client.patch(detail_url(self.space), payload, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn(next(iter(payload)), response.data)
        self.space.refresh_from_db()
        self.assertEqual(self.space.name, "Fictional Test Space")
        self.assertEqual((self.space.location.x, self.space.location.y), (-6.26, 53.35))
        self.assertEqual(self.space.space_type, "cafe")
        self.assertIsNone(self.space.has_wifi)


class EditorErrorTests(APITestBase):
    def setUp(self):
        self.login_as_editor()

    def test_put_is_not_offered(self):
        response = self.client.put(detail_url(make_space()), valid_payload(), format="json")
        self.assertEqual(response.status_code, 405)

    def test_missing_record_returns_404(self):
        missing = reverse("spaces:studyspace-detail", args=[999999])
        self.assertEqual(self.client.patch(missing, {"name": "X"}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(missing).status_code, 404)

    def test_malformed_json_returns_400(self):
        response = self.client.post(LIST_URL, data="{not valid json", content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("detail", response.data)
        self.assertFalse(StudySpace.objects.exists())
