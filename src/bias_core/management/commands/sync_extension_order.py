from __future__ import annotations

from django.core.management import CommandError
from django.core.management.base import BaseCommand
from django.db import OperationalError, ProgrammingError

from bias_core.extensions.manager import get_extension_manager


class Command(BaseCommand):
    help = "Synchronize persisted extension enabled order with dependency resolution."

    def handle(self, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Syncing extension enabled order..."))
        try:
            result = get_extension_manager().sync_enabled_extension_order()
        except (OperationalError, ProgrammingError) as exc:
            raise CommandError(
                "Django 数据库迁移尚未应用，无法同步扩展启用顺序。请先执行 python manage.py migrate。"
            ) from exc
        after = dict(result.get("after") or {})
        resolved = list(after.get("resolved") or [])
        stale = list(after.get("stale") or [])
        self.stdout.write(f"启用扩展: {len(resolved)}")
        self.stdout.write(f"过期记录: {len(stale)}")
        self.stdout.write(f"已变更: {'yes' if result.get('changed') else 'no'}")
        self.stdout.write(self.style.SUCCESS("Extension order sync complete."))
