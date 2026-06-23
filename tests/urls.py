from django.urls import path, include

from bias_core.api_runtime import build_api_application

api = build_api_application()

urlpatterns = [
    path("api/", api.urls),
]
