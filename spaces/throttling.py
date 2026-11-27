"""Rate limits for the REST API (rates are set in settings.REST_FRAMEWORK)."""
from rest_framework.permissions import SAFE_METHODS
from rest_framework.throttling import UserRateThrottle


class WriteRateThrottle(UserRateThrottle):
    """
    Limits create, update and delete requests per logged-in user ("write" rate).
    Visitors' reads are limited by AnonRateThrottle. Logged-in users are administrators,
    and their reads (for example browsing the API) need no extra limit.
    """

    scope = "write"

    def allow_request(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return super().allow_request(request, view)
