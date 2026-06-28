from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NotificationBlueprint:
    type: str
    subject_type: str | None = None
    subject_id: int | None = None
    data: dict = field(default_factory=dict)
    match_data: dict = field(default_factory=dict)
    from_user: Any | None = None

    def with_data(self, **values: Any) -> "NotificationBlueprint":
        return NotificationBlueprint(
            type=self.type,
            subject_type=self.subject_type,
            subject_id=self.subject_id,
            data={**dict(self.data or {}), **values},
            match_data=dict(self.match_data or {}),
            from_user=self.from_user,
        )

    def matching(self, **values: Any) -> "NotificationBlueprint":
        return NotificationBlueprint(
            type=self.type,
            subject_type=self.subject_type,
            subject_id=self.subject_id,
            data=dict(self.data or {}),
            match_data={**dict(self.match_data or {}), **values},
            from_user=self.from_user,
        )
