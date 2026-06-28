from __future__ import annotations

import json
from typing import Any

from ninja import Body, Router

from bias_core.admin_auth import require_staff
from bias_core.extension_detail import (
    _serialize_admin_extension,
    _serialize_admin_extension_action_payload,
    _serialize_admin_extensions_payload,
    serialize_admin_extension,
    serialize_admin_extensions_payload,
)
from bias_core.extension_service import ExtensionService
from bias_core.extension_settings_service import (
    get_extension_settings,
    save_extension_settings,
    serialize_extension_settings_schema,
)
from bias_core.extensions.exceptions import ExtensionNotFoundError, ExtensionStateError
from bias_core.extensions.registry import get_extension_registry
from bias_core.jwt_auth import AccessTokenAuth


router = Router()
ADMIN_EXTENSION_RESPONSES = {200: dict, 404: dict, 409: dict}


def _error_payload(exc: Exception, *, code: str = "extension_error") -> tuple[int, dict[str, Any]]:
    if isinstance(exc, ExtensionStateError):
        return 409, {
            "code": exc.code,
            "message": str(exc),
            "field_errors": dict(exc.details or {}),
        }
    if isinstance(exc, ExtensionNotFoundError):
        return 404, {
            "code": "extension_not_found",
            "message": str(exc),
            "field_errors": {},
        }
    return 409, {
        "code": code,
        "message": str(exc),
        "field_errors": {},
    }


def _staff_denied(request):
    denied = require_staff(request)
    return denied if denied else None


@router.get("/extensions", auth=AccessTokenAuth(), tags=["Admin"], response=ADMIN_EXTENSION_RESPONSES)
def list_extensions(request):
    denied = _staff_denied(request)
    if denied:
        return denied
    return _serialize_admin_extensions_payload(ExtensionService.list_extensions())


@router.post("/extensions/sync", auth=AccessTokenAuth(), tags=["Admin"], response=ADMIN_EXTENSION_RESPONSES)
def sync_extensions(request, payload: dict[str, Any] = Body(default_factory=dict)):
    denied = _staff_denied(request)
    if denied:
        return denied
    ExtensionService.sync_extension_packages(
        prune_missing=bool(dict(payload or {}).get("prune_missing", True)),
        request=request,
    )
    return _serialize_admin_extensions_payload(ExtensionService.list_extensions())


@router.post("/extensions/sync-order", auth=AccessTokenAuth(), tags=["Admin"], response=ADMIN_EXTENSION_RESPONSES)
def sync_extension_order(request):
    denied = _staff_denied(request)
    if denied:
        return denied
    ExtensionService.sync_enabled_extension_order(request=request)
    return _serialize_admin_extensions_payload(ExtensionService.list_extensions())


@router.post("/extensions/rebuild-frontend", auth=AccessTokenAuth(), tags=["Admin"], response=ADMIN_EXTENSION_RESPONSES)
def rebuild_extension_frontend(request, payload: dict[str, Any] = Body(default_factory=dict)):
    denied = _staff_denied(request)
    if denied:
        return denied
    data = dict(payload or {})
    result = ExtensionService.rebuild_extension_frontend_assets(
        run_build=bool(data.get("run_build", True)),
        include_disabled=bool(data.get("include_disabled", False)),
        publish=bool(data.get("publish", False)),
        request=request,
    )
    response = _serialize_admin_extensions_payload(ExtensionService.list_extensions())
    response["frontend_rebuild"] = result
    return response


@router.get("/extensions/{extension_id}", auth=AccessTokenAuth(), tags=["Admin"], response=ADMIN_EXTENSION_RESPONSES)
def get_extension_detail(request, extension_id: str):
    denied = _staff_denied(request)
    if denied:
        return denied
    try:
        extension = _get_extension(extension_id)
    except Exception as exc:
        status, payload = _error_payload(exc)
        return status, payload
    return _serialize_admin_extension_action_payload(extension)


@router.get("/extensions/{extension_id}/settings", auth=AccessTokenAuth(), tags=["Admin"], response=ADMIN_EXTENSION_RESPONSES)
def get_extension_settings_payload(request, extension_id: str):
    denied = _staff_denied(request)
    if denied:
        return denied
    try:
        return {
            "extension_id": extension_id,
            "schema": serialize_extension_settings_schema(extension_id),
            "settings": get_extension_settings(extension_id),
        }
    except Exception as exc:
        status, payload = _error_payload(exc)
        return status, payload


@router.post("/extensions/{extension_id}/settings", auth=AccessTokenAuth(), tags=["Admin"], response=ADMIN_EXTENSION_RESPONSES)
def save_extension_settings_payload(request, extension_id: str, payload: dict[str, Any] = Body(default_factory=dict)):
    denied = _staff_denied(request)
    if denied:
        return denied
    try:
        settings = save_extension_settings(extension_id, payload)
        return {
            "extension_id": extension_id,
            "schema": serialize_extension_settings_schema(extension_id),
            "settings": settings,
        }
    except Exception as exc:
        status, error_payload = _error_payload(exc)
        return status, error_payload


@router.post("/extensions/{extension_id}/install", auth=AccessTokenAuth(), tags=["Admin"], response=ADMIN_EXTENSION_RESPONSES)
def install_extension(request, extension_id: str):
    return _run_extension_action(request, lambda: ExtensionService.install_extension(extension_id, request=request))


@router.post("/extensions/{extension_id}/uninstall", auth=AccessTokenAuth(), tags=["Admin"], response=ADMIN_EXTENSION_RESPONSES)
def uninstall_extension(request, extension_id: str):
    payload = _optional_json_body(request)
    include_dependents = bool(payload.get("include_dependents", False))
    return _run_extension_action(
        request,
        lambda: ExtensionService.uninstall_extension(
            extension_id,
            include_dependents=include_dependents,
            request=request,
        ),
    )


@router.post("/extensions/{extension_id}/enable", auth=AccessTokenAuth(), tags=["Admin"], response=ADMIN_EXTENSION_RESPONSES)
def enable_extension(request, extension_id: str):
    payload = _optional_json_body(request)
    include_dependencies = bool(payload.get("include_dependencies", False))
    return _run_extension_action(
        request,
        lambda: ExtensionService.set_extension_enabled(
            extension_id,
            True,
            include_dependencies=include_dependencies,
            request=request,
        ),
    )


@router.post("/extensions/{extension_id}/disable", auth=AccessTokenAuth(), tags=["Admin"], response=ADMIN_EXTENSION_RESPONSES)
def disable_extension(request, extension_id: str):
    payload = _optional_json_body(request)
    include_dependents = bool(payload.get("include_dependents", False))
    return _run_extension_action(
        request,
        lambda: ExtensionService.set_extension_enabled(
            extension_id,
            False,
            include_dependents=include_dependents,
            request=request,
        ),
    )


@router.post("/extensions/{extension_id}/runtime-hooks/{hook_name}", auth=AccessTokenAuth(), tags=["Admin"], response=ADMIN_EXTENSION_RESPONSES)
def run_extension_runtime_hook(request, extension_id: str, hook_name: str):
    return _run_extension_action(
        request,
        lambda: ExtensionService.run_extension_runtime_hook(extension_id, hook_name, request=request),
    )


@router.post("/extensions/{extension_id}/migrations", auth=AccessTokenAuth(), tags=["Admin"], response=ADMIN_EXTENSION_RESPONSES)
def run_extension_migrations(request, extension_id: str):
    return _run_extension_action(request, lambda: ExtensionService.run_extension_migrations(extension_id, request=request))


def _run_extension_action(request, callback):
    denied = _staff_denied(request)
    if denied:
        return denied
    try:
        extension = callback()
    except Exception as exc:
        status, payload = _error_payload(exc)
        return status, payload
    return _serialize_admin_extension_action_payload(extension)


def _optional_json_body(request) -> dict[str, Any]:
    raw_body = getattr(request, "body", b"") or b""
    if not raw_body:
        return {}
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _get_extension(extension_id: str):
    from bias_core import admin_content_api as compat_module

    return compat_module.get_extension_registry().get_extension(extension_id)
