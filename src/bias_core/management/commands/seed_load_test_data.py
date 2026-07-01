from __future__ import annotations

import json
import time
from itertools import cycle
from typing import Any

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.db.models import Count, Max
from django.utils import timezone


class Command(BaseCommand):
    help = "Seed deterministic forum data for Bias load testing."
    requires_system_checks = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--users", type=int, default=1000, help="目标 load-test 用户数")
        parser.add_argument("--discussions", type=int, default=10000, help="目标 load-test 讨论数")
        parser.add_argument("--posts", type=int, default=100000, help="目标 load-test 帖子数")
        parser.add_argument("--tags", type=int, default=200, help="目标 load-test 标签数；tags 扩展缺失时跳过")
        parser.add_argument("--notifications", type=int, default=50000, help="目标 load-test 通知数；notifications 扩展缺失时跳过")
        parser.add_argument("--batch-size", type=int, default=1000, help="批量写入大小")
        parser.add_argument("--prefix", default="loadtest", help="种子数据前缀，用于幂等补齐")
        parser.add_argument("--format", choices=("text", "json"), default="text")

    def handle(self, *args, **options):
        started = time.perf_counter()
        prefix = _clean_prefix(str(options.get("prefix") or "loadtest"))
        batch_size = max(1, int(options.get("batch_size") or 1000))
        targets = {
            "users": max(0, int(options.get("users") or 0)),
            "discussions": max(0, int(options.get("discussions") or 0)),
            "posts": max(0, int(options.get("posts") or 0)),
            "tags": max(0, int(options.get("tags") or 0)),
            "notifications": max(0, int(options.get("notifications") or 0)),
        }

        with transaction.atomic():
            payload = seed_load_test_data(prefix=prefix, targets=targets, batch_size=batch_size)

        payload["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        payload["summary"] = {
            "ok": not payload["errors"],
            "created_total": sum(item.get("created", 0) for item in payload["sections"].values()),
            "skipped_optional": [
                name for name, item in payload["sections"].items() if item.get("skipped")
            ],
        }

        if options["format"] == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            self._write_text(payload)

        if payload["errors"]:
            raise CommandError("; ".join(payload["errors"]))

    def _write_text(self, payload: dict[str, Any]) -> None:
        self.stdout.write("Load-test seed completed")
        for name, item in payload["sections"].items():
            if item.get("skipped"):
                self.stdout.write(f"- {name}: skipped ({item.get('reason')})")
            else:
                self.stdout.write(
                    f"- {name}: existing={item.get('existing', 0)}, "
                    f"created={item.get('created', 0)}, target={item.get('target', 0)}"
                )


def seed_load_test_data(*, prefix: str, targets: dict[str, int], batch_size: int) -> dict[str, Any]:
    sections: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    UserModel = get_user_model()
    Discussion = _required_model("content", "Discussion")
    Post = _required_model("content", "Post")
    Tag = _optional_model("tags", "Tag")
    DiscussionTag = _optional_model("tags", "DiscussionTag")
    Notification = _optional_model("notifications", "Notification")

    sections["users"] = _seed_users(UserModel, prefix, targets["users"], batch_size)
    users = list(UserModel.objects.filter(username__startswith=f"{prefix}-user-").order_by("id")[: max(targets["users"], 1)])
    if not users and (targets["discussions"] or targets["posts"] or targets["notifications"]):
        errors.append("未能创建 load-test 用户，无法继续创建讨论、帖子或通知。")
        return {"prefix": prefix, "targets": targets, "sections": sections, "errors": errors}

    sections["discussions"] = _seed_discussions(Discussion, users, prefix, targets["discussions"], batch_size)
    discussions = list(Discussion.objects.filter(slug__startswith=f"{prefix}-discussion-").order_by("id"))
    if not discussions and targets["posts"]:
        errors.append("未能创建 load-test 讨论，无法继续创建帖子。")
        return {"prefix": prefix, "targets": targets, "sections": sections, "errors": errors}

    sections["posts"] = _seed_posts(Post, Discussion, users, discussions, prefix, targets["posts"], batch_size)
    sections["tags"] = _seed_tags(Tag, DiscussionTag, discussions, prefix, targets["tags"], batch_size)
    sections["notifications"] = _seed_notifications(Notification, users, discussions, prefix, targets["notifications"], batch_size)

    return {
        "prefix": prefix,
        "targets": targets,
        "sections": sections,
        "errors": errors,
    }


def _seed_users(UserModel, prefix: str, target: int, batch_size: int) -> dict[str, Any]:
    existing = UserModel.objects.filter(username__startswith=f"{prefix}-user-").count()
    missing = max(0, target - existing)
    if missing == 0:
        return {"target": target, "existing": existing, "created": 0}

    start = existing + 1
    created = 0
    fields = {field.name for field in UserModel._meta.fields}
    while created < missing:
        size = min(batch_size, missing - created)
        rows = []
        for number in range(start + created, start + created + size):
            row = UserModel(
                username=f"{prefix}-user-{number:08d}",
                email=f"{prefix}-user-{number:08d}@example.test",
                password="!",
            )
            if "display_name" in fields:
                row.display_name = f"Load User {number}"
            if "is_email_confirmed" in fields:
                row.is_email_confirmed = True
            if "is_active" in fields:
                row.is_active = True
            rows.append(row)
        UserModel.objects.bulk_create(rows, batch_size=batch_size)
        created += size
    return {"target": target, "existing": existing, "created": missing}


def _seed_discussions(Discussion, users: list[Any], prefix: str, target: int, batch_size: int) -> dict[str, Any]:
    existing = Discussion.objects.filter(slug__startswith=f"{prefix}-discussion-").count()
    missing = max(0, target - existing)
    if missing == 0:
        return {"target": target, "existing": existing, "created": 0}

    now = timezone.now()
    user_cycle = cycle(users)
    start = existing + 1
    created = 0
    while created < missing:
        size = min(batch_size, missing - created)
        rows = []
        for number in range(start + created, start + created + size):
            user = next(user_cycle)
            rows.append(Discussion(
                title=f"Load discussion {number}",
                slug=f"{prefix}-discussion-{number:08d}",
                user=user,
                last_posted_user=user,
                last_posted_at=now,
                comment_count=0,
                participant_count=1,
                approval_status=getattr(Discussion, "APPROVAL_APPROVED", "approved"),
                approved_at=now,
            ))
        Discussion.objects.bulk_create(rows, batch_size=batch_size)
        created += size
    return {"target": target, "existing": existing, "created": missing}


def _seed_posts(Post, Discussion, users: list[Any], discussions: list[Any], prefix: str, target: int, batch_size: int) -> dict[str, Any]:
    existing = Post.objects.filter(content__startswith=f"{prefix} load post ").count()
    missing = max(0, target - existing)
    if missing == 0:
        return {"target": target, "existing": existing, "created": 0}

    now = timezone.now()
    user_cycle = cycle(users)
    discussion_ids = [discussion.id for discussion in discussions]
    max_numbers = {
        row["discussion_id"]: int(row["max_number"] or 0)
        for row in Post.objects.filter(discussion_id__in=discussion_ids)
        .values("discussion_id")
        .annotate(max_number=Max("number"))
    }
    start = existing + 1
    created = 0
    updated_discussion_ids: set[int] = set()
    discussion_cycle = cycle(discussions)
    while created < missing:
        size = min(batch_size, missing - created)
        rows = []
        for number in range(start + created, start + created + size):
            discussion = next(discussion_cycle)
            post_number = max_numbers.get(discussion.id, 0) + 1
            max_numbers[discussion.id] = post_number
            user = next(user_cycle)
            rows.append(Post(
                discussion=discussion,
                number=post_number,
                user=user,
                type="comment",
                content=f"{prefix} load post {number}",
                content_html=f"<p>{prefix} load post {number}</p>",
                approval_status=getattr(Post, "APPROVAL_APPROVED", "approved"),
                approved_at=now,
            ))
            updated_discussion_ids.add(discussion.id)
        Post.objects.bulk_create(rows, batch_size=batch_size)
        created += size

    _refresh_discussion_summaries(Post, Discussion, updated_discussion_ids)
    return {"target": target, "existing": existing, "created": missing}


def _refresh_discussion_summaries(Post, Discussion, discussion_ids: set[int]) -> None:
    if not discussion_ids:
        return
    counts = {
        row["discussion_id"]: {
            "comment_count": int(row["comment_count"] or 0),
            "last_post_number": int(row["last_post_number"] or 0),
            "last_post_id": row["last_post_id"],
        }
        for row in Post.objects.filter(discussion_id__in=discussion_ids)
        .values("discussion_id")
        .annotate(
            comment_count=Count("id"),
            last_post_number=Max("number"),
            last_post_id=Max("id"),
        )
    }
    rows = []
    for discussion in Discussion.objects.filter(id__in=discussion_ids):
        summary = counts.get(discussion.id) or {}
        discussion.comment_count = int(summary.get("comment_count") or 0)
        discussion.last_post_number = int(summary.get("last_post_number") or 0)
        discussion.last_post_id = summary.get("last_post_id")
        rows.append(discussion)
    Discussion.objects.bulk_update(rows, ["comment_count", "last_post_number", "last_post_id"], batch_size=1000)


def _seed_tags(Tag, DiscussionTag, discussions: list[Any], prefix: str, target: int, batch_size: int) -> dict[str, Any]:
    if Tag is None:
        return {"target": target, "existing": 0, "created": 0, "skipped": True, "reason": "tags app not installed"}
    existing = Tag.objects.filter(slug__startswith=f"{prefix}-tag-").count()
    missing = max(0, target - existing)
    created = 0
    start = existing + 1
    while created < missing:
        size = min(batch_size, missing - created)
        rows = [
            Tag(
                name=f"Load Tag {number}",
                slug=f"{prefix}-tag-{number:08d}",
                description="Load test tag",
                position=number,
                is_primary=True,
            )
            for number in range(start + created, start + created + size)
        ]
        Tag.objects.bulk_create(rows, batch_size=batch_size)
        created += size

    relation_created = 0
    if DiscussionTag is not None and discussions and target:
        tags = list(Tag.objects.filter(slug__startswith=f"{prefix}-tag-").order_by("id")[:target])
        if tags:
            existing_pairs = set(DiscussionTag.objects.filter(
                discussion_id__in=[discussion.id for discussion in discussions],
                tag_id__in=[tag.id for tag in tags],
            ).values_list("discussion_id", "tag_id"))
            tag_cycle = cycle(tags)
            rows = []
            for discussion in discussions:
                tag = next(tag_cycle)
                pair = (discussion.id, tag.id)
                if pair in existing_pairs:
                    continue
                rows.append(DiscussionTag(discussion_id=discussion.id, tag_id=tag.id))
                if len(rows) >= batch_size:
                    DiscussionTag.objects.bulk_create(rows, batch_size=batch_size, ignore_conflicts=True)
                    relation_created += len(rows)
                    rows = []
            if rows:
                DiscussionTag.objects.bulk_create(rows, batch_size=batch_size, ignore_conflicts=True)
                relation_created += len(rows)
            _refresh_tag_summaries(Tag, DiscussionTag, tags)

    return {
        "target": target,
        "existing": existing,
        "created": missing,
        "discussion_relations_created": relation_created,
    }


def _refresh_tag_summaries(Tag, DiscussionTag, tags: list[Any]) -> None:
    tag_ids = [tag.id for tag in tags]
    counts = {
        row["tag_id"]: int(row["discussion_count"] or 0)
        for row in DiscussionTag.objects.filter(tag_id__in=tag_ids)
        .values("tag_id")
        .annotate(discussion_count=Count("discussion_id"))
    }
    for tag in tags:
        tag.discussion_count = counts.get(tag.id, 0)
    Tag.objects.bulk_update(tags, ["discussion_count"], batch_size=1000)


def _seed_notifications(Notification, users: list[Any], discussions: list[Any], prefix: str, target: int, batch_size: int) -> dict[str, Any]:
    if Notification is None:
        return {"target": target, "existing": 0, "created": 0, "skipped": True, "reason": "notifications app not installed"}
    existing = Notification.objects.filter(type=f"{prefix}.load").count()
    missing = max(0, target - existing)
    if missing == 0:
        return {"target": target, "existing": existing, "created": 0}
    user_cycle = cycle(users)
    actor_cycle = cycle(users[1:] or users)
    discussion_cycle = cycle(discussions or [None])
    created = 0
    start = existing + 1
    while created < missing:
        size = min(batch_size, missing - created)
        rows = []
        for number in range(start + created, start + created + size):
            discussion = next(discussion_cycle)
            rows.append(Notification(
                user=next(user_cycle),
                from_user=next(actor_cycle),
                type=f"{prefix}.load",
                subject_type="discussion" if discussion is not None else "",
                subject_id=discussion.id if discussion is not None else None,
                data={"index": number, "title": f"Load notification {number}"},
                is_read=number % 3 == 0,
                is_deleted=False,
            ))
        Notification.objects.bulk_create(rows, batch_size=batch_size)
        created += size
    return {"target": target, "existing": existing, "created": missing}


def _required_model(app_label: str, model_name: str):
    try:
        return apps.get_model(app_label, model_name)
    except LookupError as exc:
        raise CommandError(f"缺少必需模型 {app_label}.{model_name}，请先启用 foundation 扩展并执行迁移。") from exc


def _optional_model(app_label: str, model_name: str):
    try:
        return apps.get_model(app_label, model_name)
    except LookupError:
        return None


def _clean_prefix(raw: str) -> str:
    prefix = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in raw.strip().lower())
    return prefix.strip("-_") or "loadtest"
