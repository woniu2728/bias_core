from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PaginationService:
    page: int = 1
    page_size: int = 20
    total: int = 0

    @classmethod
    def paginate(cls, queryset, request, **kwargs) -> dict:
        page = int(request.GET.get("page", 1))
        page_size = int(request.GET.get("page_size", 20))
        start = (page - 1) * page_size
        end = start + page_size
        total = queryset.count()
        items = queryset[start:end]
        return {
            "data": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
