from __future__ import annotations

from typing import Any


def apply_model_visibility_scope(queryset, request, model=None) -> Any:
    return queryset


def apply_related_model_visibility_subquery(queryset, relation: str, request) -> Any:
    return queryset


def can_view_model_instance(instance, request) -> bool:
    return True

def get_core_model_visibility_scopers():
    return []

def register_core_model_visibility_scoper(*args, **kwargs):
    pass

