from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("spaces", views.StudySpaceViewSet, basename="studyspace")

app_name = "spaces"
urlpatterns = [
    path("", views.home, name="home"),
    path("api/", include(router.urls)),
]
