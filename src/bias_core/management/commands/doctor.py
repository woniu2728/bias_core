from __future__ import annotations

from django.core.management.base import BaseCommand
from bias_core.runtime_checks import collect_runtime_readiness


class Command(BaseCommand):
    help = "Bias system health check — inspect runtime status and detect risks."

    def handle(self, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Bias Doctor — System Health Check"))
        self.stdout.write("")

        readiness = collect_runtime_readiness()

        self.stdout.write(f"Database:      {readiness.get('database_label', 'unknown')}")
        self.stdout.write(f"Cache driver:  {readiness.get('cache_driver', 'unknown')}")
        self.stdout.write(f"Realtime:      {readiness.get('realtime_driver', 'unknown')}")
        self.stdout.write(f"Queue:         {readiness.get('queue_driver', 'unknown')}")
        self.stdout.write(f"Redis enabled: {readiness.get('redis_enabled', False)}")
        self.stdout.write("")

        risks = readiness.get("runtime_risks", [])
        if risks:
            self.stdout.write(self.style.WARNING(f"Found {len(risks)} issue(s):"))
            for risk in risks:
                level = risk.get("level", "info")
                title = risk.get("title", "")
                message = risk.get("message", "")
                if level == "danger":
                    self.stdout.write(self.style.ERROR(f"  [!] [{level.upper()}] {title}"))
                else:
                    self.stdout.write(self.style.WARNING(f"  [!] {title}"))
                self.stdout.write(f"      {message}")
        else:
            self.stdout.write(self.style.SUCCESS("No issues detected. System looks healthy."))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Doctor check complete."))
