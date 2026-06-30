from django.urls import path

from bias_core.api_runtime import build_api_application
from bias_core.extensions.bootstrap import get_extension_host


def build_test_api_application():
    return build_api_application(extension_host=get_extension_host())


api = build_test_api_application()

urlpatterns = [
    path("api/", api.urls),
]


def rebuild_api_urlpatterns():
    global api, urlpatterns
    api = build_test_api_application()
    urlpatterns = [
        path("api/", api.urls),
    ]
    return urlpatterns
