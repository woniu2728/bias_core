from __future__ import annotations

from django.core.management.base import BaseCommand

from bias_core.extensions.manager import get_extension_manager


class Command(BaseCommand):
    help = "Discover installed extensions and sync runtime state."

    def handle(self, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Syncing extensions..."))
        result = get_extension_manager().sync_extension_packages()
        discovered = list(result.get("discovered") or [])
        created = list(result.get("created") or [])
        updated = list(result.get("updated") or [])
        pruned = list(result.get("pruned") or [])

        if discovered:
            self.stdout.write(self.style.SUCCESS(f"Found {len(discovered)} extension(s):"))
            for extension_id in discovered:
                self.stdout.write(f"  - {extension_id}")
        else:
            self.stdout.write(self.style.WARNING("No extensions found."))

        self.stdout.write(f"创建: {len(created)}")
        self.stdout.write(f"更新: {len(updated)}")
        self.stdout.write(f"剪枝: {len(pruned)}")
        self.stdout.write("包锁定: 已更新")
        self.stdout.write(self.style.SUCCESS("Extension sync complete."))
