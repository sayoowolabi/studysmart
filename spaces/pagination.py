"""Pagination for the study-space list endpoint."""
from rest_framework.pagination import PageNumberPagination


class StudySpacePagination(PageNumberPagination):
    """
    GET /api/spaces/ returns 100 records per page by default. Clients may ask for up to
    1000 with ?page_size= (the map page does, so it usually needs one request).
    The search endpoints (nearby, nearest) are not paginated: their size is limited by
    the radius and by the map's result count instead.
    """

    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 1000
