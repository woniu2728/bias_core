from __future__ import annotations

import json
from typing import Any

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction


MEMBER_PERMISSIONS = (
    "viewForum",
    "startDiscussion",
    "startDiscussionWithoutApproval",
    "discussion.reply",
    "discussion.typing",
    "discussion.editOwn",
    "discussion.deleteOwn",
    "post.editOwn",
    "post.deleteOwn",
    "replyWithoutApproval",
    "viewUserList",
    "searchUsers",
)

MODERATOR_PERMISSIONS = (
    "viewForum",
    "discussion.reply",
    "replyWithoutApproval",
    "discussion.edit",
    "discussion.rename",
    "discussion.hide",
    "discussion.delete",
    "post.edit",
    "post.hide",
    "post.delete",
    "admin.approval.view",
    "admin.approval.approve",
    "admin.approval.reject",
)

LOAD_TEST_NOTIFICATION_PREFERENCES = {
    "notify_post_liked": False,
    "notify_post_reply": False,
    "notify_new_post": False,
    "notify_user_mentioned": False,
    "notify_account_status": False,
}


class Command(BaseCommand):
    help = "Create or update deterministic login actors for Bias load testing."
    requires_system_checks = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--username", default="loadtest-auth-user", help="普通登录态压测用户名")
        parser.add_argument("--email", default="", help="普通登录态压测邮箱；默认按 username@example.test 生成")
        parser.add_argument("--password", default="loadtest-password", help="普通登录态压测密码")
        parser.add_argument("--moderator-username", default="loadtest-moderator", help="版主写入压测用户名")
        parser.add_argument("--moderator-email", default="", help="版主写入压测邮箱；默认按 username@example.test 生成")
        parser.add_argument("--moderator-password", default="loadtest-password", help="版主写入压测密码")
        parser.add_argument("--format", choices=("text", "json"), default="text")

    def handle(self, *args, **options):
        username = _clean_username(options.get("username") or "loadtest-auth-user")
        moderator_username = _clean_username(options.get("moderator_username") or "loadtest-moderator")
        password = str(options.get("password") or "")
        moderator_password = str(options.get("moderator_password") or "")
        if not password or not moderator_password:
            raise CommandError("必须提供非空 --password 和 --moderator-password")
        if username == moderator_username:
            raise CommandError("普通用户和版主用户必须使用不同 username")

        Group = _required_model("users", "Group")
        Permission = _required_model("users", "Permission")
        AccessToken = _optional_model("users", "AccessToken")
        UserModel = get_user_model()

        with transaction.atomic():
            member_group = _ensure_group(
                Group,
                name="Member",
                defaults={"name_singular": "Member", "name_plural": "Members"},
            )
            moderator_group = _ensure_group(
                Group,
                name="Moderator",
                defaults={
                    "name_singular": "Moderator",
                    "name_plural": "Moderators",
                    "color": "#80349E",
                    "icon": "fas fa-shield-alt",
                },
            )
            member_permissions = _ensure_permissions(Permission, member_group, MEMBER_PERMISSIONS)
            moderator_permissions = _ensure_permissions(Permission, moderator_group, MODERATOR_PERMISSIONS)

            auth_user = _ensure_user(
                UserModel,
                username=username,
                email=options.get("email") or _default_email(username),
                password=password,
                is_staff=False,
                is_superuser=False,
            )
            moderator = _ensure_user(
                UserModel,
                username=moderator_username,
                email=options.get("moderator_email") or _default_email(moderator_username),
                password=moderator_password,
                is_staff=True,
                is_superuser=False,
            )

            member_group.users.add(auth_user)
            member_group.users.add(moderator)
            moderator_group.users.add(moderator)
            token_cleanup = _clear_access_tokens(AccessToken, [auth_user, moderator])

        payload = {
            "ok": True,
            "actors": {
                "auth": _serialize_actor(
                    auth_user,
                    password=password,
                    groups=["Member"],
                    permissions=member_permissions,
                ),
                "moderator": _serialize_actor(
                    moderator,
                    password=moderator_password,
                    groups=["Member", "Moderator"],
                    permissions=sorted(set(member_permissions) | set(moderator_permissions)),
                ),
            },
            "commands": {
                "forum_main_auth": {
                    "login_username": username,
                    "login_password": password,
                },
                "forum_write": {
                    "login_username": username,
                    "login_password": password,
                },
                "forum_write_moderation": {
                    "login_username": moderator_username,
                    "login_password": moderator_password,
                },
            },
            "token_cleanup": token_cleanup,
        }

        if options["format"] == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            self._write_text(payload)

    def _write_text(self, payload: dict[str, Any]) -> None:
        self.stdout.write("Load-test actors prepared")
        for name, actor in payload["actors"].items():
            self.stdout.write(
                f"- {name}: username={actor['username']}, groups={','.join(actor['groups'])}, "
                f"usable_password={actor['usable_password']}"
            )


def _ensure_user(UserModel, *, username: str, email: str, password: str, is_staff: bool, is_superuser: bool):
    defaults = {
        "email": email,
        "is_active": True,
        "is_staff": is_staff,
        "is_superuser": is_superuser,
    }
    fields = {field.name for field in UserModel._meta.fields}
    if "is_email_confirmed" in fields:
        defaults["is_email_confirmed"] = True
    if "display_name" in fields:
        defaults["display_name"] = username
    if "preferences" in fields:
        defaults["preferences"] = dict(LOAD_TEST_NOTIFICATION_PREFERENCES)

    user, created = UserModel.objects.get_or_create(username=username, defaults=defaults)
    updates = []
    for field, value in defaults.items():
        if hasattr(user, field) and getattr(user, field) != value:
            setattr(user, field, value)
            updates.append(field)
    if user.email != email:
        user.email = email
        updates.append("email")
    user.set_password(password)
    updates.append("password")
    if created:
        user.save()
    else:
        user.save(update_fields=sorted(set(updates)))
    return user


def _ensure_group(Group, *, name: str, defaults: dict[str, Any]):
    group, created = Group.objects.get_or_create(name=name, defaults=defaults)
    if created:
        return group
    updates = []
    for field, value in defaults.items():
        if hasattr(group, field) and not getattr(group, field):
            setattr(group, field, value)
            updates.append(field)
    if updates:
        group.save(update_fields=updates)
    return group


def _ensure_permissions(Permission, group, permissions: tuple[str, ...]) -> list[str]:
    for permission in permissions:
        Permission.objects.get_or_create(group=group, permission=permission)
    return sorted(permissions)


def _clear_access_tokens(AccessToken, users: list[Any]) -> dict[str, int]:
    if AccessToken is None:
        return {"deleted": 0, "skipped": True, "reason": "users.AccessToken model not installed"}
    deleted, details = AccessToken.objects.filter(user__in=users).delete()
    return {"deleted": int(deleted), "details": {key: int(value) for key, value in details.items()}}


def _serialize_actor(user, *, password: str, groups: list[str], permissions: list[str]) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "password": password,
        "usable_password": user.has_usable_password(),
        "email_confirmed": bool(getattr(user, "is_email_confirmed", True)),
        "is_active": bool(getattr(user, "is_active", True)),
        "is_staff": bool(getattr(user, "is_staff", False)),
        "is_superuser": bool(getattr(user, "is_superuser", False)),
        "groups": groups,
        "permissions": permissions,
    }


def _required_model(app_label: str, model_name: str):
    try:
        return apps.get_model(app_label, model_name)
    except LookupError as exc:
        raise CommandError(f"缺少必需模型 {app_label}.{model_name}，请先启用 users 扩展并执行迁移。") from exc


def _optional_model(app_label: str, model_name: str):
    try:
        return apps.get_model(app_label, model_name)
    except LookupError:
        return None


def _clean_username(raw: str) -> str:
    username = raw.strip()
    if not username:
        raise CommandError("username 不能为空")
    return username


def _default_email(username: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in username.lower())
    return f"{safe}@example.test"
