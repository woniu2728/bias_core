from __future__ import annotations

from django.core.management.base import BaseCommand
from bias_core.extensions.discovery import get_extension_host


class Command(BaseCommand):
    help = "Discover installed extensions and sync runtime state."

    def handle(self, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Syncing extensions..."))
        host = get_extension_host()
        host.discover()
        count = len(host.extensions)
        if count:
            self.stdout.write(self.style.SUCCESS(f"Found {count} extension(s):"))
            for ext_id in host.extensions:
                self.stdout.write(f"  - {ext_id}")
        else:
            self.stdout.write(self.style.WARNING("No extensions found."))
        self.stdout.write(self.style.SUCCESS("Extension sync complete."))
