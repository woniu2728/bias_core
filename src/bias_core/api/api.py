from django.middleware.csrf import get_token
from ninja import Router

from bias_core.api.auth import get_optional_user
from bias_core.api.jwt_auth import AccessTokenAuth
from bias_core.extensions.platform import get_enabled_theme
from bias_core.markdown_service import MarkdownService
from bias_core.runtime_state import get_runtime_status
from bias_core.schemas import MarkdownPreviewInSchema, MarkdownPreviewOutSchema
from bias_core.settings_service import get_public_forum_settings

router = Router(tags=["System"])


@router.get("/status")
def system_status(request):
    runtime = get_runtime_status()
    return {
        "status": runtime.state,
        "state": runtime.state,
        "current_version": runtime.current_version,
    }


@router.get("/system/status", tags=["System"])
def get_system_status(request):
    status = get_runtime_status()
    return {
        "state": status.state,
        "message": status.message,
        "current_version": status.current_version,
        "installed_version": status.installed_version,
    }


@router.get("/csrf", tags=["Auth"])
def get_csrf_token(request):
    return {"csrfToken": get_token(request)}


@router.get("/forum", tags=["Forum"])
def get_forum_settings(request):
    return get_public_forum_settings(user=get_optional_user(request))


@router.get("/forum/theme", tags=["Forum"])
def get_forum_theme(request):
    return {"theme": get_enabled_theme()}


@router.post("/preview", response=MarkdownPreviewOutSchema, tags=["Forum"])
def preview_markdown(request, payload: MarkdownPreviewInSchema):
    return {"html": MarkdownService.render(payload.content or "", sanitize=True)}


@router.get("/search", tags=["Forum"])
def search(request, q: str = ""):
    return {"query": q or "", "results": [], "total": 0}


@router.post("/discussions", tags=["Forum"])
def create_discussion_placeholder(request):
    return {"error": "discussions extension is not available", "code": "extension_unavailable"}


@router.get("/users/me", auth=AccessTokenAuth(), tags=["Auth"])
def current_user(request):
    user = request.auth
    return {
        "id": user.id,
        "username": user.get_username(),
        "email": getattr(user, "email", ""),
        "is_staff": bool(getattr(user, "is_staff", False)),
        "is_superuser": bool(getattr(user, "is_superuser", False)),
    }
