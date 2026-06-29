from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from django.http import JsonResponse


JSONAPI_CONTENT_TYPE = "application/vnd.api+json"


@dataclass(frozen=True)
class ResourceQueryOptions:
    includes: tuple[str, ...] = ()
    fields: tuple[str, ...] | None = None


def parse_csv_param(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(
        item.strip()
        for item in value.split(",")
        if item and item.strip()
    )


def parse_resource_query_options(request, resource: str) -> ResourceQueryOptions:
    includes = parse_csv_param(_get_query_param(request, "include"))
    fields = parse_csv_param(_get_query_param(request, f"fields[{resource}]"))
    return ResourceQueryOptions(
        includes=includes,
        fields=fields or None,
    )


def merge_resource_includes(*include_groups: Iterable[str]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for group in include_groups:
        for item in group:
            normalized = (item or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
    return tuple(ordered)


def wants_jsonapi_response(request_or_context) -> bool:
    request = request_or_context
    if isinstance(request_or_context, dict):
        request = request_or_context.get("request")
    accept = str(getattr(request, "META", {}).get("HTTP_ACCEPT", "") or "")
    return JSONAPI_CONTENT_TYPE in accept.lower()


def jsonapi_response(payload, *, status: int = 200) -> JsonResponse:
    return JsonResponse(
        payload,
        status=status,
        content_type=JSONAPI_CONTENT_TYPE,
        safe=isinstance(payload, dict),
    )


def serialize_resource_jsonapi_response(
    registry,
    resource: str,
    data,
    context: dict,
    *,
    resource_options: ResourceQueryOptions | None = None,
    include: Iterable[str] = (),
    many: bool = False,
    status: int = 200,
):
    if not wants_jsonapi_response(context):
        return None
    resource_options = resource_options or ResourceQueryOptions()
    document = registry.serialize_jsonapi_document(
        resource,
        data,
        context,
        only=resource_options.fields,
        include=merge_resource_includes(include, resource_options.includes),
        many=many,
    )
    return jsonapi_response(document, status=status)


def serialize_resource_plain(
    registry,
    resource: str,
    data,
    context: dict,
    *,
    resource_options: ResourceQueryOptions | None = None,
    include: Iterable[str] = (),
):
    resource_options = resource_options or ResourceQueryOptions()
    return registry.serialize(
        resource,
        data,
        context,
        only=resource_options.fields,
        include=merge_resource_includes(include, resource_options.includes),
    )


def apply_resource_preloads(
    registry,
    queryset,
    resource: str,
    *,
    context: dict | None = None,
    resource_options: ResourceQueryOptions | None = None,
    default_includes: Iterable[str] = (),
):
    resource_options = resource_options or ResourceQueryOptions()
    return registry.apply_preload_plan(
        queryset,
        resource,
        context,
        only=resource_options.fields,
        include=merge_resource_includes(default_includes, resource_options.includes),
    )


def _get_query_param(request, key: str) -> str | None:
    getter = getattr(getattr(request, "GET", None), "get", None)
    if getter is None:
        return None
    value = getter(key)
    if value is None:
        return None
    return str(value)

