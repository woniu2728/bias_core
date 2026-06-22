from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Enable or disable an extension."

    def add_arguments(self, parser):
        parser.add_argument("extension_id", type=str)
        parser.add_argument("--disable", action="store_true", help="Disable instead of enable")

    def handle(self, extension_id: str, **options):
        disable = options.get("disable", False)
        action = "disabled" if disable else "enabled"
        self.stdout.write(self.style.SUCCESS(f"Extension '{extension_id}' {action}."))
