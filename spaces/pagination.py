"""Pagination for the study-space list endpoint."""
from rest_framework.pagination import PageNumberPagination


class StudySpacePagination(PageNumberPagination):
    """
    GET /api/spaces/ returns 100 records per page by default. Clients can ask for up to
    1000 with ?page_size=. The map page does this, so it usually needs only one request.
    The search endpoints (nearby and nearest) are not paginated. Their size is already
    limited by the radius and by the map's result count.
    """

    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 1000
