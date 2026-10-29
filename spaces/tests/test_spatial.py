"""Spatial API tests with fictional points and squares whose distances are known.

Along a meridian, 0.01 degrees of latitude is about 1,112 m (2*pi*R/36,000 with
R of about 6,371 km), and 0.005 degrees is about 556 m.
"""
from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.urls import reverse
from rest_framework.test import APITestCase

from spaces.models import AdministrativeArea, StudySpace

NEARBY_URL = reverse("spaces:studyspace-nearby")
NEAREST_URL = reverse("spaces:studyspace-nearest")
COVERAGE_URL = reverse("spaces:area-coverage")
AREAS_URL = reverse("spaces:area-list")

ORIGIN_LAT, ORIGIN_LNG = 53.35, -6.26


def make_space(name, latitude, longitude=ORIGIN_LNG, **overrides):
    values = {
        "name": name, "space_type": "cafe",
        "location": Point(longitude, latitude, srid=4326),
    }
    values.update(overrides)
    return StudySpace.objects.create(**values)


def make_area(name, bbox):
    square = Polygon.from_bbox(bbox)
    square.srid = 4326
    return AdministrativeArea.objects.create(
        name=name, source_id=name.lower(), boundary=MultiPolygon(square, srid=4326),
    )


def search(url, **params):
    params = {"lat": ORIGIN_LAT, "lng": ORIGIN_LNG, **params}
    return url + "?" + "&".join(f"{key}={value}" for key, value in params.items())


class NearbyTests(APITestCase):
    def setUp(self):
        make_space("Origin Library", ORIGIN_LAT, space_type="library")
        make_space("Unknown-Seat Cafe", ORIGIN_LAT + 0.005)
        make_space("Seated Cafe", ORIGIN_LAT + 0.01, indoor_seating=True)

    def test_results_are_ordered_with_distances_in_metres(self):
        with self.assertNumQueries(1):
            response = self.client.get(search(NEARBY_URL, radius=2000))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["name"] for item in response.data],
            ["Origin Library", "Unknown-Seat Cafe", "Seated Cafe"],
        )
        for item, expected in zip(response.data, (0, 556, 1112)):
            self.assertAlmostEqual(item["distance_m"], expected, delta=1)

    def test_radius_edge(self):
        names = lambda radius: [i["name"] for i in self.client.get(search(NEARBY_URL, radius=radius)).data]
        self.assertNotIn("Seated Cafe", names(1100))
        self.assertIn("Seated Cafe", names(1120))

    def test_type_and_confirmed_indoor_seating_filters(self):
        response = self.client.get(search(NEARBY_URL, radius=2000, type="cafe", indoor_seating="true"))
        self.assertEqual([item["name"] for item in response.data], ["Seated Cafe"])

    def test_combined_facility_filters_require_every_facility_confirmed(self):
        # The map sends several facility filters at once; they must combine with AND.
        make_space("Seated Wi-Fi Cafe", ORIGIN_LAT + 0.002, indoor_seating=True, has_wifi=True)
        make_space("Seated Unknown Wi-Fi Cafe", ORIGIN_LAT + 0.003, indoor_seating=True)
        make_space("Seated No Wi-Fi Cafe", ORIGIN_LAT + 0.004, indoor_seating=True, has_wifi=False)
        response = self.client.get(search(NEARBY_URL, radius=2000, type="cafe", indoor_seating="true", has_wifi="true"))
        self.assertEqual([item["name"] for item in response.data], ["Seated Wi-Fi Cafe"])

        nearest = self.client.get(search(NEAREST_URL, indoor_seating="true", has_wifi="true"))
        self.assertEqual(nearest.data["name"], "Seated Wi-Fi Cafe")

    def test_maximum_radius_is_accepted(self):
        response = self.client.get(search(NEARBY_URL, radius=10000))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 3)

    def test_unknown_seating_filter_combines_with_type_and_radius(self):
        make_space("Standing Cafe", ORIGIN_LAT + 0.003, indoor_seating=False)
        make_space("Far Unknown Cafe", ORIGIN_LAT + 0.05)  # about 5.6 km away
        names = lambda **filters: [i["name"] for i in self.client.get(search(NEARBY_URL, radius=2000, **filters)).data]
        # Unknown matches only NULL: not the confirmed or "no" seating, and nothing beyond the radius.
        self.assertEqual(names(indoor_seating="unknown"), ["Origin Library", "Unknown-Seat Cafe"])
        self.assertEqual(names(type="cafe", indoor_seating="unknown"), ["Unknown-Seat Cafe"])
        self.assertEqual(names(type="cafe", indoor_seating="false"), ["Standing Cafe"])

    def test_no_matches_returns_empty_list(self):
        response = self.client.get(search(NEARBY_URL, lat=53.0, radius=1000))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_invalid_parameters_are_rejected(self):
        for params, field in (
            ({"lat": 91, "radius": 100}, "lat"),
            ({"lng": -181, "radius": 100}, "lng"),
            ({"lat": "north", "radius": 100}, "lat"),
            ({"lat": "nan", "radius": 100}, "lat"),
            ({"lng": "inf", "radius": 100}, "lng"),
            ({"radius": 0}, "radius"),
            ({"radius": -5}, "radius"),
            ({"radius": 10001}, "radius"),
            ({"radius": "nan"}, "radius"),
            ({}, "radius"),
        ):
            with self.subTest(params=params):
                response = self.client.get(search(NEARBY_URL, **params))
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.data)

    def test_missing_coordinates_and_invalid_filters_are_rejected(self):
        response = self.client.get(NEARBY_URL + "?radius=100")
        self.assertEqual(response.status_code, 400)
        self.assertIn("lat", response.data)
        self.assertIn("lng", response.data)
        response = self.client.get(search(NEARBY_URL, radius=100, indoor_seating="maybe"))
        self.assertEqual(response.status_code, 400)


class NearestTests(APITestCase):
    def setUp(self):
        make_space("Unknown-Seat Cafe", ORIGIN_LAT + 0.005)
        make_space("Seated Cafe", ORIGIN_LAT + 0.01, indoor_seating=True)

    def test_nearest_with_distance(self):
        with self.assertNumQueries(1):
            response = self.client.get(search(NEAREST_URL))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "Unknown-Seat Cafe")
        self.assertAlmostEqual(response.data["distance_m"], 556, delta=1)

    def test_filters_apply_before_choosing_nearest(self):
        response = self.client.get(search(NEAREST_URL, indoor_seating="true"))
        self.assertEqual(response.data["name"], "Seated Cafe")
        self.assertAlmostEqual(response.data["distance_m"], 1112, delta=1)

    def test_no_match_returns_404(self):
        response = self.client.get(search(NEAREST_URL, type="library"))
        self.assertEqual(response.status_code, 404)
        self.assertIn("detail", response.data)

    def test_invalid_coordinates_are_rejected(self):
        self.assertEqual(self.client.get(search(NEAREST_URL, lat=-90.1)).status_code, 400)

    def test_missing_parameters_and_invalid_filters_are_rejected(self):
        for url, fields in (
            (NEAREST_URL, {"lat", "lng"}),
            (NEAREST_URL + "?lng=-6.26", {"lat"}),
            (search(NEAREST_URL, has_wifi="sometimes"), {"has_wifi"}),
            (search(NEAREST_URL, type="university"), {"type"}),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(set(response.data), fields)


class CoverageTests(APITestCase):
    def setUp(self):
        # Two fictional squares sharing the edge at longitude -6.25.
        make_area("West", (-6.30, 53.30, -6.25, 53.40))
        make_area("East", (-6.25, 53.30, -6.20, 53.40))
        make_space("West Library", 53.35, -6.28, space_type="library")
        make_space("West Cafe", 53.35, -6.27)
        make_space("East Cafe", 53.35, -6.22)
        make_space("Border Cafe", 53.35, -6.25)
        make_space("Outside Cafe", 53.35, -6.10)

    def test_counts_per_area(self):
        with self.assertNumQueries(3):  # one for the area list, one count per area
            response = self.client.get(COVERAGE_URL)
        self.assertEqual(response.status_code, 200)
        counts = {
            area["name"]: (area["library_count"], area["cafe_count"], area["total_count"])
            for area in response.data
        }
        # The border café is covered by both squares; the outside café by neither.
        self.assertEqual(counts, {"West": (1, 2, 3), "East": (0, 2, 2)})
        self.assertEqual([area["name"] for area in response.data], ["East", "West"])
        self.assertEqual(
            set(response.data[0]),
            {"id", "source_id", "name", "library_count", "cafe_count", "total_count"},
        )

    def test_containment_uses_the_exact_polygon_not_its_bounding_box(self):
        # An L-shaped area: its bounding box includes the empty top-right notch.
        l_shape = Polygon((
            (-5.00, 53.00), (-4.90, 53.00), (-4.90, 53.05), (-4.95, 53.05),
            (-4.95, 53.10), (-5.00, 53.10), (-5.00, 53.00),
        ), srid=4326)
        AdministrativeArea.objects.create(
            name="L-Shape", source_id="l-shape", boundary=MultiPolygon(l_shape, srid=4326),
        )
        make_space("Lower Arm Cafe", 53.02, -4.92)
        make_space("Upper Arm Library", 53.08, -4.98, space_type="library")
        make_space("Corner Cafe", 53.00, -5.00)           # on a vertex: covered
        make_space("Notch Cafe", 53.08, -4.92)            # inside the bounding box only
        make_space("Just Outside Cafe", 53.02, -5.00001)  # about 0.7 m west of the edge
        area = next(a for a in self.client.get(COVERAGE_URL).data if a["name"] == "L-Shape")
        self.assertEqual((area["library_count"], area["cafe_count"], area["total_count"]), (1, 2, 3))

    def test_area_without_spaces_has_zero_counts(self):
        make_area("Empty", (-5.0, 53.0, -4.9, 53.1))
        empty = next(a for a in self.client.get(COVERAGE_URL).data if a["name"] == "Empty")
        self.assertEqual((empty["library_count"], empty["cafe_count"], empty["total_count"]), (0, 0, 0))

    def test_no_areas_returns_empty_list(self):
        AdministrativeArea.objects.all().delete()
        response = self.client.get(COVERAGE_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_coverage_is_read_only(self):
        self.assertEqual(self.client.post(COVERAGE_URL, {}).status_code, 405)


class AreaBoundaryTests(APITestCase):
    def setUp(self):
        make_area("West", (-6.30, 53.30, -6.25, 53.40))
        make_area("East", (-6.25, 53.30, -6.20, 53.40))

    def test_boundaries_are_geojson_in_longitude_latitude_order(self):
        with self.assertNumQueries(1):
            response = self.client.get(AREAS_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["type"], "FeatureCollection")
        self.assertEqual(
            [feature["properties"]["name"] for feature in response.data["features"]],
            ["East", "West"],
        )
        west = response.data["features"][1]
        self.assertEqual(west["type"], "Feature")
        self.assertEqual(west["properties"], {"source_id": "west", "name": "West"})
        self.assertEqual(west["geometry"]["type"], "MultiPolygon")
        # GeoJSON positions are [longitude, latitude]: Dublin is about [-6.3, 53.3], not [53.3, -6.3].
        ring = west["geometry"]["coordinates"][0][0]
        self.assertEqual(ring[0], ring[-1])
        self.assertEqual(
            {tuple(position) for position in ring},
            {(-6.3, 53.3), (-6.3, 53.4), (-6.25, 53.4), (-6.25, 53.3)},
        )

    def test_coordinates_are_rounded_to_five_decimal_places(self):
        AdministrativeArea.objects.all().delete()
        make_area("Precise", (-6.123456789, 53.123456789, -6.1, 53.2))
        ring = self.client.get(AREAS_URL).data["features"][0]["geometry"]["coordinates"][0][0]
        self.assertIn([-6.12346, 53.12346], ring)

    def test_no_areas_returns_empty_collection(self):
        AdministrativeArea.objects.all().delete()
        response = self.client.get(AREAS_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"type": "FeatureCollection", "features": []})

    def test_boundaries_are_read_only(self):
        self.assertEqual(self.client.post(AREAS_URL, {}).status_code, 405)
