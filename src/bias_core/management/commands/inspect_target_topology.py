from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlparse

from django.conf import settings
from django.core.management import BaseCommand, CommandError
from django.core.management.base import CommandParser


class Command(BaseCommand):
    help = "Output machine-readable target-environment topology evidence for the P2 gate."
    requires_system_checks = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--web-nodes", type=int, default=None, help="Number of target web nodes.")
        parser.add_argument("--worker-nodes", type=int, default=None, help="Number of target worker nodes.")
        parser.add_argument("--scheduler-nodes", type=int, default=None, help="Number of target scheduler nodes.")
        parser.add_argument("--image", default="", help="Container image or release artifact identifier.")
        parser.add_argument("--app-version", default="", help="Application version deployed to all roles.")
        parser.add_argument("--database", default="", help="Shared database endpoint or identifier.")
        parser.add_argument("--redis", default="", help="Shared Redis/cache/channel-layer endpoint or identifier.")
        parser.add_argument("--load-balancer", default="", help="Public load balancer, ingress, or proxy identifier.")
        parser.add_argument("--require-multi-node", action="store_true", help="Require at least two web nodes.")
        parser.add_argument("--format", choices=("text", "json"), default="text")

    def handle(self, *args, **options):
        payload = self._build_payload(options)
        if options["format"] == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            self._write_text(payload)
        if not payload["summary"]["ok"]:
            raise CommandError("Target topology evidence is incomplete")

    def _build_payload(self, options: dict[str, Any]) -> dict[str, Any]:
        roles = {
            "web": self._option_int(options, "web_nodes", "BIAS_TOPOLOGY_WEB_NODES", default=1),
            "worker": self._option_int(options, "worker_nodes", "BIAS_TOPOLOGY_WORKER_NODES", default=0),
            "scheduler": self._option_int(options, "scheduler_nodes", "BIAS_TOPOLOGY_SCHEDULER_NODES", default=0),
        }
        require_multi_node = bool(options.get("require_multi_node"))
        artifacts = {
            "image": self._option_str(options, "image", "BIAS_TOPOLOGY_IMAGE"),
            "version": self._option_str(options, "app_version", "BIAS_TOPOLOGY_VERSION")
            or str(getattr(settings, "BIAS_VERSION", "") or ""),
        }
        shared_services = {
            "database": self._option_str(options, "database", "BIAS_TOPOLOGY_DATABASE"),
            "redis": self._option_str(options, "redis", "BIAS_TOPOLOGY_REDIS"),
            "load_balancer": self._option_str(options, "load_balancer", "BIAS_TOPOLOGY_LOAD_BALANCER"),
        }
        errors = self._validate(roles, artifacts, shared_services, require_multi_node=require_multi_node)
        warnings = []
        if roles["web"] == 1 and not require_multi_node:
            warnings.append("single web node reported; pass --require-multi-node for target P2 evidence")
        return {
            "roles": roles,
            "artifacts": artifacts,
            "shared_services": shared_services,
            "errors": errors,
            "warnings": warnings,
            "summary": {
                "ok": not errors,
                "error_count": len(errors),
                "warning_count": len(warnings),
                "multi_node": roles["web"] >= 2 and roles["worker"] >= 1 and roles["scheduler"] >= 1,
                "require_multi_node": require_multi_node,
            },
        }

    def _validate(
        self,
        roles: dict[str, int],
        artifacts: dict[str, str],
        shared_services: dict[str, str],
        *,
        require_multi_node: bool,
    ) -> list[str]:
        errors = []
        if roles["web"] < 1:
            errors.append("web nodes must be at least 1")
        if roles["worker"] < 1:
            errors.append("worker nodes must be at least 1")
        if roles["scheduler"] < 1:
            errors.append("scheduler nodes must be at least 1")
        if require_multi_node and roles["web"] < 2:
            errors.append("multi-node target evidence requires at least 2 web nodes")
        image = artifacts.get("image", "")
        version = artifacts.get("version", "")
        if not image:
            errors.append("artifacts.image is required")
        elif image in {"local-production-smoke", "latest"} or self._has_placeholder(image):
            errors.append("artifacts.image must identify a target release image")
        if not version:
            errors.append("artifacts.version is required")
        elif self._has_placeholder(version):
            errors.append("artifacts.version must not contain placeholders")
        database = shared_services.get("database", "")
        redis = shared_services.get("redis", "")
        load_balancer = shared_services.get("load_balancer", "")
        for key, value in (("database", database), ("redis", redis)):
            if not value:
                errors.append(f"shared_services.{key} is required")
            elif self._has_placeholder(value) or self._is_local_service(value):
                errors.append(f"shared_services.{key} must identify a shared target service")
        if not load_balancer:
            errors.append("shared_services.load_balancer is required")
        elif self._has_placeholder(load_balancer) or urlparse(load_balancer).scheme != "https":
            errors.append("shared_services.load_balancer must use https")
        return errors

    def _has_placeholder(self, value: str) -> bool:
        return "<" in value and ">" in value

    def _is_local_service(self, value: str) -> bool:
        parsed = urlparse(value)
        host = (parsed.hostname or value).split(":", 1)[0].strip().lower()
        return host in {"", "localhost", "127.0.0.1", "::1", "postgres", "redis"}

    def _option_int(self, options: dict[str, Any], key: str, env_key: str, *, default: int) -> int:
        raw_value = options.get(key)
        if raw_value is None:
            raw_value = os.environ.get(env_key, default)
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            raise CommandError(f"{key.replace('_', '-')} must be an integer")

    def _option_str(self, options: dict[str, Any], key: str, env_key: str) -> str:
        return str(options.get(key) or os.environ.get(env_key, "") or "").strip()

    def _write_text(self, payload: dict[str, Any]) -> None:
        marker = "OK" if payload["summary"]["ok"] else "FAILED"
        self.stdout.write(f"Target topology: {marker}")
        self.stdout.write(
            f"- roles: web={payload['roles']['web']}, worker={payload['roles']['worker']}, "
            f"scheduler={payload['roles']['scheduler']}"
        )
        if payload["errors"]:
            for error in payload["errors"]:
                self.stdout.write(f"- error: {error}")
