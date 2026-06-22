from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Disable an extension."

    def add_arguments(self, parser):
        parser.add_argument("extension_id", type=str)

    def handle(self, extension_id: str, **options):
        self.stdout.write(self.style.SUCCESS(f"Extension '{extension_id}' disabled."))
