from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from django.conf import settings
from django.core.management import BaseCommand, CommandError
from django.core.management.base import CommandParser


class Command(BaseCommand):
    help = "Output the target-environment P2 evidence run plan and expected archive files."
    requires_system_checks = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--base-url", required=True, help="Target public HTTPS base URL.")
        parser.add_argument("--report-dir", required=True, help="Target operations evidence directory.")
        parser.add_argument("--p0-report-dir", required=True, help="Target P0 capacity evidence directory.")
        parser.add_argument("--p1-report-dir", required=True, help="Target P1 capacity evidence directory.")
        parser.add_argument("--backup-dir", default="<durable-backup-uri>", help="Durable target backup directory.")
        parser.add_argument("--discussion-id", default="<discussion-id>", help="Discussion id for WebSocket broadcast smoke.")
        parser.add_argument("--load-username", default="<load-user>", help="Authenticated load-test username.")
        parser.add_argument("--load-password", default="<load-password>", help="Authenticated load-test password.")
        parser.add_argument("--moderator-username", default="<moderator-user>", help="Moderator load-test username.")
        parser.add_argument("--moderator-password", default="<moderator-password>", help="Moderator load-test password.")
        parser.add_argument("--redis-broker-url", default="<redis-broker-url>", help="Target Celery broker URL for queue worker smoke.")
        parser.add_argument("--redis-result-backend", default="<redis-result-backend>", help="Target Celery result backend URL for queue worker smoke.")
        parser.add_argument("--web-nodes", default="<web-count>", help="Target web node count for topology evidence.")
        parser.add_argument("--worker-nodes", default="<worker-count>", help="Target worker node count for topology evidence.")
        parser.add_argument("--scheduler-nodes", default="<scheduler-count>", help="Target scheduler node count for topology evidence.")
        parser.add_argument("--image", default="<image-or-release>", help="Target image or release identifier for topology evidence.")
        parser.add_argument("--app-version", default="<version>", help="Target application version for topology evidence.")
        parser.add_argument("--database-endpoint", default="<db-endpoint>", help="Target shared database endpoint for topology evidence.")
        parser.add_argument("--redis-endpoint", default="<redis-endpoint>", help="Target shared Redis endpoint for topology evidence.")
        parser.add_argument("--write-plan-file", default="", help="Write the JSON plan to this path, creating parent directories.")
        parser.add_argument("--write-safe-script", default="", help="Write a PowerShell script containing safe unattended archive commands only.")
        parser.add_argument("--write-safe-shell-script", default="", help="Write a POSIX shell script containing safe unattended archive commands only.")
        parser.add_argument("--format", choices=("text", "json"), default="text")

    def handle(self, *args, **options):
        payload = self._build_payload(options)
        plan_file_path = str(options.get("write_plan_file") or "").strip()
        if plan_file_path:
            self._write_json_file(self._resolve_path(plan_file_path), payload)
            payload["plan_file_path"] = str(self._resolve_path(plan_file_path))
        safe_script_path = str(options.get("write_safe_script") or "").strip()
        if safe_script_path:
            self._write_safe_script(self._resolve_path(safe_script_path), payload)
            payload["safe_script_path"] = str(self._resolve_path(safe_script_path))
        safe_shell_script_path = str(options.get("write_safe_shell_script") or "").strip()
        if safe_shell_script_path:
            self._write_safe_shell_script(self._resolve_path(safe_shell_script_path), payload)
            payload["safe_shell_script_path"] = str(self._resolve_path(safe_shell_script_path))
        if options["format"] == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            self._write_text(payload)
        if not payload["summary"]["ok"]:
            raise CommandError("Target environment evidence plan has blocking errors")

    def _build_payload(self, options: dict[str, Any]) -> dict[str, Any]:
        base_url = str(options["base_url"]).rstrip("/")
        report_dir = self._resolve_path(options["report_dir"])
        p0_report_dir = self._resolve_path(options["p0_report_dir"])
        p1_report_dir = self._resolve_path(options["p1_report_dir"])
        backup_dir = str(options["backup_dir"])
        errors = []
        warnings = []
        if not base_url.startswith("https://"):
            errors.append("base_url must start with https:// for target-environment evidence")
        commands = []
        commands.extend(self._ops_commands(base_url, report_dir, backup_dir, options))
        commands.extend(self._p0_commands(base_url, p0_report_dir))
        commands.extend(self._p1_commands(base_url, p1_report_dir, options))
        plan_file = self._resolve_path(options["write_plan_file"]) if str(options.get("write_plan_file") or "").strip() else report_dir / "target-environment-evidence-plan.json"
        remediation_checklist = report_dir / "target-environment-remediation-checklist.md"
        commands.append(self._cmd(
            "validate_target_environment_evidence",
            "final_validation",
            report_dir / "target-environment-evidence-validation.json",
            (
                "python manage.py validate_target_environment_evidence "
                f"--report-dir {self._quote(report_dir)} "
                f"--p0-report-dir {self._quote(p0_report_dir)} "
                f"--p1-report-dir {self._quote(p1_report_dir)} "
                f"--plan-file {self._quote(plan_file)} "
                f"--write-remediation-checklist {self._quote(remediation_checklist)} "
                "--require-multi-node --format json"
            ),
            execution_group="final_validation",
            validation_profile={
                "plan_file": str(plan_file),
                "remediation_checklist": str(remediation_checklist),
                "require_multi_node": "true",
            },
        ))
        missing_outputs = [item for item in commands if not Path(item["output_file"]).exists()]
        destructive_commands = [item for item in commands if item["destructive"]]
        manual_approval_commands = [item for item in commands if item["manual_approval_required"]]
        unattended_commands = [item for item in commands if item["safe_to_run_unattended"]]
        safe_archive_ready_commands = [item for item in commands if item["safe_archive_ready"]]
        dependency_blocked_commands = [item for item in commands if item["requires_completed_commands"]]
        final_validation_commands = [item for item in commands if item["execution_group"] == "final_validation"]
        substitution_required_commands = [item for item in commands if item["requires_substitution"]]
        target_value_required_commands = [item for item in commands if item["target_value_errors"]]
        excluded_from_safe = [item for item in commands if not item["safe_archive_ready"]]
        command_groups = self._command_groups(commands)
        execution_queues = self._execution_queues(commands)
        dependency_execution_waves = self._dependency_execution_waves(commands)
        return {
            "schema_version": 1,
            "base_url": base_url,
            "report_dir": str(report_dir),
            "p0_report_dir": str(p0_report_dir),
            "p1_report_dir": str(p1_report_dir),
            "backup_dir": backup_dir,
            "remediation_checklist": str(remediation_checklist),
            "commands": commands,
            "safe_archive_commands": [item["archive_command"] for item in safe_archive_ready_commands],
            "safe_archive_manifest": [self._safe_manifest_item(item) for item in safe_archive_ready_commands],
            "excluded_from_safe_archive": [self._excluded_item(item) for item in excluded_from_safe],
            "command_groups": command_groups,
            "execution_sequence": self._execution_sequence(command_groups),
            "execution_queues": execution_queues,
            "dependency_execution_waves": dependency_execution_waves,
            "manual_approval_commands": [self._list_item(item) for item in manual_approval_commands],
            "final_validation_commands": [self._list_item(item) for item in final_validation_commands],
            "substitution_required_commands": [self._list_item(item) for item in substitution_required_commands],
            "target_value_required_commands": [self._list_item(item) for item in target_value_required_commands],
            "dependency_blocked_commands": [self._list_item(item) for item in dependency_blocked_commands],
            "errors": errors,
            "warnings": warnings,
            "summary": {
                "ok": not errors,
                "command_count": len(commands),
                "missing_output_count": len(missing_outputs),
                "destructive_command_count": len(destructive_commands),
                "manual_approval_command_count": len(manual_approval_commands),
                "safe_unattended_command_count": len(unattended_commands),
                "safe_archive_ready_command_count": len(safe_archive_ready_commands),
                "excluded_from_safe_archive_count": len(excluded_from_safe),
                "substitution_required_command_count": len(substitution_required_commands),
                "target_value_required_command_count": len(target_value_required_commands),
                "dependency_blocked_command_count": len(dependency_blocked_commands),
                "dependency_execution_wave_count": len(dependency_execution_waves),
                "final_validation_command_count": len(final_validation_commands),
                "execution_queue_counts": self._queue_counts(execution_queues),
                "error_count": len(errors),
                "warning_count": len(warnings),
                "executes_commands": False,
            },
        }

    def _list_item(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "key": item["key"],
            "execution_group": item["execution_group"],
            "destructive": item["destructive"],
            "manual_approval_required": item["manual_approval_required"],
            "requires_substitution": item["requires_substitution"],
            "substitution_tokens": item["substitution_tokens"],
            "target_value_errors": item["target_value_errors"],
            "safe_to_run_unattended": item["safe_to_run_unattended"],
            "safe_archive_ready": item["safe_archive_ready"],
            "requires_completed_commands": item["requires_completed_commands"],
            "backup_dir": item["backup_dir"],
            "redis_broker_url": item["redis_broker_url"],
            "redis_result_backend": item["redis_result_backend"],
            "topology": item["topology"],
            "capacity_profile": item["capacity_profile"],
            "websocket_profile": item["websocket_profile"],
            "runtime_integration_profile": item["runtime_integration_profile"],
            "validation_profile": item["validation_profile"],
            "command": item["command"],
            "output_file": item["output_file"],
            "stderr_file": item["stderr_file"],
            "archive_command": item["archive_command"],
        }

    def _command_groups(self, commands: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for item in commands:
            group = str(item.get("execution_group") or "unknown")
            payload = grouped.setdefault(group, {
                "command_count": 0,
                "command_keys": [],
                "commands": [],
                "output_files": [],
                "stderr_files": [],
                "archive_commands": [],
                "manual_approval_required": False,
                "destructive": False,
                "safe_to_run_unattended": group == "safe_unattended",
                "safe_archive_ready": group == "safe_unattended",
                "requires_substitution": False,
                "target_value_required": False,
                "dependency_blocked": False,
                "requires_completed_commands": [],
            })
            payload["command_count"] += 1
            payload["command_keys"].append(item["key"])
            payload["commands"].append(item["command"])
            payload["output_files"].append(item["output_file"])
            payload["stderr_files"].append(item["stderr_file"])
            payload["archive_commands"].append(item["archive_command"])
            if item["manual_approval_required"]:
                payload["manual_approval_required"] = True
            if item["destructive"]:
                payload["destructive"] = True
            if not item["safe_to_run_unattended"]:
                payload["safe_to_run_unattended"] = False
            if not item["safe_archive_ready"]:
                payload["safe_archive_ready"] = False
            if item["requires_substitution"]:
                payload["requires_substitution"] = True
            if item["target_value_errors"]:
                payload["target_value_required"] = True
            if item["requires_completed_commands"]:
                payload["dependency_blocked"] = True
                for dependency in item["requires_completed_commands"]:
                    if dependency not in payload["requires_completed_commands"]:
                        payload["requires_completed_commands"].append(dependency)
        return dict(sorted(grouped.items()))

    def _execution_sequence(self, command_groups: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        known_order = [
            ("safe_unattended", "run safe unattended archive commands"),
            ("requires_substitution", "replace substitution tokens before running"),
            ("target_value_required", "fix target value errors before running"),
            ("maintenance_approval", "run only in an approved maintenance window"),
            ("destructive_approval", "run only after approval, durable backup, and rollback staffing are confirmed"),
            ("final_validation", "run only after all evidence-producing commands have been archived"),
        ]
        sequence = []
        step = 1
        seen = set()
        for group, policy in known_order:
            data = command_groups.get(group)
            if not data:
                continue
            sequence.append(self._sequence_item(step, group, data, policy))
            seen.add(group)
            step += 1
        for group in sorted(set(command_groups) - seen):
            sequence.append(self._sequence_item(
                step,
                group,
                command_groups[group],
                "manual review required before running",
            ))
            step += 1
        return sequence

    def _sequence_item(self, step: int, group: str, data: dict[str, Any], policy: str) -> dict[str, Any]:
        return {
            "step": step,
            "groups": [group],
            "command_keys": data["command_keys"],
            "command_count": data["command_count"],
            "safe_to_run_unattended": data["safe_to_run_unattended"],
            "safe_archive_ready": data["safe_archive_ready"],
            "manual_approval_required": data["manual_approval_required"],
            "destructive": data["destructive"],
            "requires_substitution": data["requires_substitution"],
            "target_value_required": data["target_value_required"],
            "dependency_blocked": data["dependency_blocked"],
            "requires_completed_commands": data["requires_completed_commands"],
            "policy": policy,
        }

    def _execution_queues(self, commands: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        queues = {
            "safe_unattended": {
                "policy": "eligible for unattended archive execution after target values are reviewed",
                "commands": [],
            },
            "requires_substitution": {
                "policy": "replace substitution tokens before running",
                "commands": [],
            },
            "target_value_required": {
                "policy": "fix target value errors before running",
                "commands": [],
            },
            "dependency_blocked": {
                "policy": "run only after requires_completed_commands have been archived",
                "commands": [],
            },
            "maintenance_approval": {
                "policy": "run only in an approved maintenance window",
                "commands": [],
            },
            "destructive_approval": {
                "policy": "run only after destructive approval and durable backup confirmation",
                "commands": [],
            },
            "final_validation": {
                "policy": "run only after all evidence-producing commands have been archived",
                "commands": [],
            },
        }
        for item in commands:
            command_ref = self._queue_command(item)
            if item["safe_to_run_unattended"]:
                queues["safe_unattended"]["commands"].append(command_ref)
            if item["requires_substitution"]:
                queues["requires_substitution"]["commands"].append(command_ref)
            if item["target_value_errors"]:
                queues["target_value_required"]["commands"].append(command_ref)
            if item["requires_completed_commands"]:
                queues["dependency_blocked"]["commands"].append(command_ref)
            if item["execution_group"] == "maintenance_approval" or (
                item["manual_approval_required"] and not item["destructive"]
            ):
                queues["maintenance_approval"]["commands"].append(command_ref)
            if item["destructive"]:
                queues["destructive_approval"]["commands"].append(command_ref)
            if item["execution_group"] == "final_validation":
                queues["final_validation"]["commands"].append(command_ref)
        return {key: self._queue_payload(value) for key, value in queues.items()}

    def _queue_command(self, item: dict[str, Any]) -> dict[str, Any]:
        return self._list_item(item)

    def _queue_payload(self, queue: dict[str, Any]) -> dict[str, Any]:
        commands = [item for item in queue["commands"] if isinstance(item, dict)]
        return {
            "policy": str(queue.get("policy") or ""),
            "command_count": len(commands),
            "command_keys": [str(item.get("key") or "") for item in commands if item.get("key")],
            "archive_commands": [str(item.get("archive_command") or "") for item in commands if item.get("archive_command")],
            "commands": commands,
        }

    def _queue_counts(self, execution_queues: dict[str, dict[str, Any]]) -> dict[str, int]:
        return {
            key: int(value.get("command_count") or 0)
            for key, value in execution_queues.items()
            if isinstance(value, dict)
        }

    def _dependency_execution_waves(self, commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
        command_by_key = {str(item.get("key") or ""): item for item in commands}
        depth_cache: dict[str, int] = {}

        def depth_for(key: str, stack: tuple[str, ...] = ()) -> int:
            if key in depth_cache:
                return depth_cache[key]
            if key in stack:
                return 0
            command = command_by_key.get(key)
            if not command:
                return 0
            dependencies = [
                dependency
                for dependency in command.get("requires_completed_commands", [])
                if dependency in command_by_key
            ]
            if not dependencies:
                depth_cache[key] = 0
                return 0
            depth_cache[key] = 1 + max(depth_for(dependency, stack + (key,)) for dependency in dependencies)
            return depth_cache[key]

        grouped: dict[int, list[dict[str, Any]]] = {}
        for command in commands:
            if not command.get("requires_completed_commands"):
                continue
            grouped.setdefault(depth_for(str(command.get("key") or "")), []).append(command)
        waves = []
        for index, depth in enumerate(sorted(grouped), start=1):
            wave_commands = grouped[depth]
            waves.append({
                "wave": index,
                "dependency_depth": depth,
                "command_count": len(wave_commands),
                "command_keys": [item["key"] for item in wave_commands],
                "requires_completed_commands": self._unique_dependencies(wave_commands),
                "commands": [self._list_item(item) for item in wave_commands],
            })
        return waves

    def _unique_dependencies(self, commands: list[dict[str, Any]]) -> list[str]:
        dependencies = []
        for command in commands:
            for dependency in command.get("requires_completed_commands", []):
                if dependency not in dependencies:
                    dependencies.append(dependency)
        return dependencies

    def _safe_manifest_item(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "key": item["key"],
            "phase": item["phase"],
            "execution_group": item["execution_group"],
            "output_file": item["output_file"],
            "stderr_file": item["stderr_file"],
            "exists": item["exists"],
            "safe_archive_ready": item["safe_archive_ready"],
            "requires_completed_commands": item["requires_completed_commands"],
            "backup_dir": item["backup_dir"],
            "redis_broker_url": item["redis_broker_url"],
            "redis_result_backend": item["redis_result_backend"],
            "topology": item["topology"],
            "capacity_profile": item["capacity_profile"],
            "websocket_profile": item["websocket_profile"],
            "runtime_integration_profile": item["runtime_integration_profile"],
            "validation_profile": item["validation_profile"],
            "command": item["command"],
            "archive_command": item["archive_command"],
        }

    def _excluded_item(self, item: dict[str, Any]) -> dict[str, Any]:
        reasons = []
        if item["destructive"]:
            reasons.append("destructive")
        if item["manual_approval_required"]:
            reasons.append("manual_approval_required")
        if item["requires_substitution"]:
            reasons.append("requires_substitution")
        if item["target_value_errors"]:
            reasons.append("target_value_required")
        if item["requires_completed_commands"]:
            reasons.append("requires_completed_commands")
        if item["execution_group"] == "final_validation":
            reasons.append("final_validation")
        return {
            "key": item["key"],
            "phase": item["phase"],
            "execution_group": item["execution_group"],
            "output_file": item["output_file"],
            "exclude_reasons": reasons or ["not_safe_to_run_unattended"],
            "substitution_tokens": item["substitution_tokens"],
            "target_value_errors": item["target_value_errors"],
            "safe_to_run_unattended": item["safe_to_run_unattended"],
            "safe_archive_ready": item["safe_archive_ready"],
            "requires_completed_commands": item["requires_completed_commands"],
            "backup_dir": item["backup_dir"],
            "redis_broker_url": item["redis_broker_url"],
            "redis_result_backend": item["redis_result_backend"],
            "topology": item["topology"],
            "capacity_profile": item["capacity_profile"],
            "websocket_profile": item["websocket_profile"],
            "runtime_integration_profile": item["runtime_integration_profile"],
            "validation_profile": item["validation_profile"],
            "archive_command": item["archive_command"],
        }

    def _ops_commands(self, base_url: str, report_dir: Path, backup_dir: str, options: dict[str, Any]) -> list[dict[str, Any]]:
        discussion_id = str(options["discussion_id"])
        redis_broker_url = str(options["redis_broker_url"])
        redis_result_backend = str(options["redis_result_backend"])
        web_nodes = str(options["web_nodes"])
        worker_nodes = str(options["worker_nodes"])
        scheduler_nodes = str(options["scheduler_nodes"])
        image = str(options["image"])
        app_version = str(options["app_version"])
        database_endpoint = str(options["database_endpoint"])
        redis_endpoint = str(options["redis_endpoint"])
        return [
            self._cmd("strict_health", "ops", report_dir / "health-strict.json", f"curl -f {base_url}/api/health?strict=1", base_url=base_url),
            self._cmd(
                "https_http_smoke",
                "ops",
                report_dir / "smoke-http-p95.json",
                f"python manage.py smoke_http_p95 --base-url {base_url} --fail-on-threshold --format json",
                base_url=base_url,
            ),
            self._cmd(
                "external_websocket",
                "ops",
                report_dir / "load-websocket-external-20.json",
                f"python manage.py load_test_websocket --base-url {base_url} --connections 20 --discussion-id {discussion_id} --p95-threshold-ms 1000 --broadcast-p95-threshold-ms 1000 --fail-on-threshold --format json",
                base_url=base_url,
                websocket_profile={
                    "connections": "20",
                    "discussion_id": discussion_id,
                    "p95_threshold_ms": "1000",
                    "broadcast_p95_threshold_ms": "1000",
                    "fail_on_threshold": "true",
                },
            ),
            self._cmd("queue_worker", "ops", report_dir / "smoke-queue-worker.json", f"python manage.py smoke_queue_worker --broker-url {redis_broker_url} --result-backend {redis_result_backend} --timeout 45 --format json", redis_broker_url=redis_broker_url, redis_result_backend=redis_result_backend, target_value_errors=self._redis_url_errors(redis_broker_url, field_name="redis_broker_url") + self._redis_url_errors(redis_result_backend, field_name="redis_result_backend")),
            self._cmd("install_dry_run", "ops", report_dir / "install-forum-dry-run.json", "python manage.py install_forum --database postgres --config instance/site.json --non-interactive --dry-run --format json"),
            self._cmd("upgrade_dry_run", "ops", report_dir / "upgrade-forum-dry-run.json", "python manage.py upgrade_forum --config instance/site.json --dry-run --non-interactive --format json"),
            self._cmd("backup", "ops", report_dir / "backup-forum.json", f"python manage.py backup_forum --config instance/site.json --backup-dir {backup_dir} --format json", backup_dir=backup_dir, target_value_errors=self._backup_dir_errors(backup_dir)),
            self._cmd("backup_verification", "ops", report_dir / "verify-forum-backup.json", f"python manage.py verify_forum_backup --config instance/site.json --backup-dir {backup_dir} --format json", backup_dir=backup_dir, target_value_errors=self._backup_dir_errors(backup_dir)),
            self._cmd(
                "upgrade_executed",
                "ops",
                report_dir / "upgrade-forum-executed.json",
                "python manage.py upgrade_forum --config instance/site.json --non-interactive --format json",
                manual_approval_required=True,
            ),
            self._cmd("post_upgrade_strict_health", "ops", report_dir / "post-upgrade-health-strict.json", f"curl -f {base_url}/api/health?strict=1", base_url=base_url, requires_completed_commands=["upgrade_executed"]),
            self._cmd("post_upgrade_http_smoke", "ops", report_dir / "post-upgrade-smoke-http-p95.json", f"python manage.py smoke_http_p95 --base-url {base_url} --fail-on-threshold --format json", base_url=base_url, requires_completed_commands=["upgrade_executed"]),
            self._cmd("post_upgrade_queue_worker", "ops", report_dir / "post-upgrade-smoke-queue-worker.json", f"python manage.py smoke_queue_worker --broker-url {redis_broker_url} --result-backend {redis_result_backend} --timeout 45 --format json", redis_broker_url=redis_broker_url, redis_result_backend=redis_result_backend, target_value_errors=self._redis_url_errors(redis_broker_url, field_name="redis_broker_url") + self._redis_url_errors(redis_result_backend, field_name="redis_result_backend"), requires_completed_commands=["upgrade_executed"]),
            self._cmd("rollback_plan", "ops", report_dir / "plan-forum-rollback-with-backups.json", f"python manage.py plan_forum_rollback --config instance/site.json --backup-dir {backup_dir} --require-existing-backups --format json", backup_dir=backup_dir, target_value_errors=self._backup_dir_errors(backup_dir)),
            self._cmd("restore_rehearsal", "ops", report_dir / "rehearse-forum-restore.json", f"python manage.py rehearse_forum_restore --config instance/site.json --backup-dir {backup_dir} --format json", backup_dir=backup_dir, target_value_errors=self._backup_dir_errors(backup_dir), requires_completed_commands=["backup_verification"]),
            self._cmd("restore_dry_run", "ops", report_dir / "restore-forum-backup-dry-run.json", f"python manage.py restore_forum_backup --config instance/site.json --backup-dir {backup_dir} --dry-run --format json", backup_dir=backup_dir, target_value_errors=self._backup_dir_errors(backup_dir), requires_completed_commands=["backup_verification", "restore_rehearsal"]),
            self._cmd("live_restore", "ops", report_dir / "restore-forum-backup-live.json", f"python manage.py restore_forum_backup --config instance/site.json --backup-dir {backup_dir} --i-understand-this-overwrites-live-data --confirm-phrase \"restore live forum data\" --format json", backup_dir=backup_dir, destructive=True, target_value_errors=self._backup_dir_errors(backup_dir), requires_completed_commands=["backup_verification", "restore_dry_run"]),
            self._cmd(
                "runtime_integrations",
                "ops",
                report_dir / "smoke-runtime-integrations.json",
                "python manage.py smoke_runtime_integrations --smtp-connect --storage-write --require-smtp-connect --require-storage-write --require-object-storage --fail-on-warning --format json",
                runtime_integration_profile={
                    "smtp_connect": "true",
                    "storage_write": "true",
                    "require_smtp_connect": "true",
                    "require_storage_write": "true",
                    "require_object_storage": "true",
                    "fail_on_warning": "true",
                },
            ),
            self._cmd(
                "multi_node_topology",
                "ops",
                report_dir / "multi-node-topology.json",
                f"python manage.py inspect_target_topology --web-nodes {web_nodes} --worker-nodes {worker_nodes} --scheduler-nodes {scheduler_nodes} --image {image} --app-version {app_version} --database {database_endpoint} --redis {redis_endpoint} --load-balancer {base_url} --require-multi-node --format json",
                base_url=base_url,
                topology={
                    "web_nodes": web_nodes,
                    "worker_nodes": worker_nodes,
                    "scheduler_nodes": scheduler_nodes,
                    "image": image,
                    "app_version": app_version,
                    "database_endpoint": database_endpoint,
                    "redis_endpoint": redis_endpoint,
                    "load_balancer": base_url,
                },
                target_value_errors=self._topology_errors(web_nodes, worker_nodes, scheduler_nodes, image, app_version, database_endpoint, redis_endpoint, base_url),
            ),
        ]

    def _p0_commands(self, base_url: str, report_dir: Path) -> list[dict[str, Any]]:
        return [
            self._cmd(
                "p0_forum_main",
                "p0_capacity",
                report_dir / "forum-main-300s.json",
                f"python manage.py load_test_http --base-url {base_url} --profile forum-main --concurrency 20 --duration 300 --fail-on-threshold --format json",
                base_url=base_url,
                capacity_profile={
                    "profile": "forum-main",
                    "concurrency": "20",
                    "duration": "300",
                },
            ),
        ]

    def _p1_commands(self, base_url: str, report_dir: Path, options: dict[str, Any]) -> list[dict[str, Any]]:
        user = str(options["load_username"])
        password = str(options["load_password"])
        moderator = str(options["moderator_username"])
        moderator_password = str(options["moderator_password"])
        discussion_id = str(options["discussion_id"])
        return [
            self._cmd("p1_forum_main_auth", "p1_capacity", report_dir / "forum-main-auth-300s.json", f"python manage.py load_test_http --base-url {base_url} --profile forum-main-auth --login-username {user} --login-password {password} --concurrency 20 --duration 300 --fail-on-threshold --format json", base_url=base_url, capacity_profile={"profile": "forum-main-auth", "login_username": user, "concurrency": "20", "duration": "300"}),
            self._cmd("p1_forum_write", "p1_capacity", report_dir / "forum-write-120s.json", f"python manage.py load_test_http --base-url {base_url} --profile forum-write --login-username {user} --login-password {password} --discussion-id {discussion_id} --concurrency 5 --duration 120 --fail-on-threshold --format json", base_url=base_url, capacity_profile={"profile": "forum-write", "login_username": user, "discussion_id": discussion_id, "concurrency": "5", "duration": "120"}),
            self._cmd("p1_forum_write_mixed", "p1_capacity", report_dir / "forum-write-mixed-120s.json", f"python manage.py load_test_http --base-url {base_url} --profile forum-write-mixed --login-username {user} --login-password {password} --prepare-isolated-targets --cleanup-isolated-targets --concurrency 5 --duration 120 --fail-on-threshold --format json", base_url=base_url, capacity_profile={"profile": "forum-write-mixed", "login_username": user, "concurrency": "5", "duration": "120", "prepare_isolated_targets": "true", "cleanup_isolated_targets": "true"}, requires_completed_commands=["p1_forum_write"]),
            self._cmd("p1_forum_upload", "p1_capacity", report_dir / "forum-upload-120s.json", f"python manage.py load_test_http --base-url {base_url} --profile forum-upload --login-username {user} --login-password {password} --concurrency 5 --duration 120 --fail-on-threshold --format json", base_url=base_url, capacity_profile={"profile": "forum-upload", "login_username": user, "concurrency": "5", "duration": "120"}),
            self._cmd("p1_forum_moderation", "p1_capacity", report_dir / "forum-write-moderation-60s.json", f"python manage.py load_test_http --base-url {base_url} --profile forum-write-moderation --login-username {moderator} --login-password {moderator_password} --prepare-isolated-targets --cleanup-isolated-targets --concurrency 2 --duration 60 --fail-on-threshold --format json", base_url=base_url, capacity_profile={"profile": "forum-write-moderation", "login_username": moderator, "concurrency": "2", "duration": "60", "prepare_isolated_targets": "true", "cleanup_isolated_targets": "true"}, requires_completed_commands=["p1_forum_write_mixed"]),
        ]

    def _cmd(
        self,
        key: str,
        phase: str,
        output_file: Path,
        command: str,
        *,
        base_url: str = "",
        backup_dir: str = "",
        redis_broker_url: str = "",
        redis_result_backend: str = "",
        topology: dict[str, str] | None = None,
        capacity_profile: dict[str, str] | None = None,
        websocket_profile: dict[str, str] | None = None,
        runtime_integration_profile: dict[str, str] | None = None,
        validation_profile: dict[str, str] | None = None,
        destructive: bool = False,
        manual_approval_required: bool = False,
        execution_group: str = "",
        target_value_errors: list[str] | None = None,
        requires_completed_commands: list[str] | None = None,
    ) -> dict[str, Any]:
        archive_command = (
            f"{command} > {self._quote(output_file)} "
            f"2> {self._quote(output_file.with_suffix('.stderr.txt'))}"
        )
        substitution_tokens = self._substitution_tokens(archive_command)
        requires_substitution = bool(substitution_tokens)
        target_value_errors = target_value_errors or []
        requires_completed_commands = requires_completed_commands or []
        approval_required = destructive or manual_approval_required
        if destructive:
            execution_group = "destructive_approval"
        elif approval_required:
            execution_group = "maintenance_approval"
        elif execution_group:
            execution_group = execution_group
        elif requires_substitution:
            execution_group = "requires_substitution"
        elif target_value_errors:
            execution_group = "target_value_required"
        else:
            execution_group = "safe_unattended"
        safe_to_run_unattended = execution_group == "safe_unattended" and not requires_substitution and not target_value_errors
        safe_archive_ready = safe_to_run_unattended and not requires_completed_commands
        return {
            "key": key,
            "phase": phase,
            "output_file": str(output_file),
            "stderr_file": str(output_file.with_suffix(".stderr.txt")),
            "exists": output_file.exists(),
            "base_url": base_url,
            "backup_dir": backup_dir,
            "redis_broker_url": redis_broker_url,
            "redis_result_backend": redis_result_backend,
            "topology": topology or {},
            "capacity_profile": capacity_profile or {},
            "websocket_profile": websocket_profile or {},
            "runtime_integration_profile": runtime_integration_profile or {},
            "validation_profile": validation_profile or {},
            "destructive": destructive,
            "manual_approval_required": approval_required,
            "requires_substitution": requires_substitution,
            "substitution_tokens": substitution_tokens,
            "target_value_errors": target_value_errors,
            "safe_to_run_unattended": safe_to_run_unattended,
            "safe_archive_ready": safe_archive_ready,
            "requires_completed_commands": requires_completed_commands,
            "execution_group": execution_group,
            "command": command,
            "archive_command": archive_command,
        }

    def _substitution_tokens(self, command: str) -> list[str]:
        return sorted(set(re.findall(r"<[^<>]+>", command)))

    def _backup_dir_errors(self, backup_dir: str) -> list[str]:
        value = backup_dir.strip().replace("\\", "/").lower()
        if self._substitution_tokens(backup_dir):
            return []
        if not value or value.startswith(("file://", "sqlite://")):
            return ["backup_dir must be a durable target-environment backup location"]
        if "://" in value:
            return []
        if (
            value.startswith("/app/")
            or value.startswith("/tmp/")
            or value.startswith("/var/tmp/")
            or value.startswith("backups/")
            or "/tmp/" in value
            or "/project/tmp/" in value
            or value[1:3] == ":/" and "/tmp/" in value
        ):
            return ["backup_dir must be a durable target-environment backup location"]
        return []

    def _redis_url_errors(self, value: str, *, field_name: str) -> list[str]:
        if self._substitution_tokens(value):
            return []
        parsed = urlparse(value)
        host = (parsed.hostname or value).split(":", 1)[0].strip().lower()
        if host in {"", "localhost", "127.0.0.1", "::1", "redis"}:
            return [f"{field_name} must identify a shared target Redis service"]
        return []

    def _topology_errors(
        self,
        web_nodes: str,
        worker_nodes: str,
        scheduler_nodes: str,
        image: str,
        app_version: str,
        database_endpoint: str,
        redis_endpoint: str,
        base_url: str,
    ) -> list[str]:
        values = [web_nodes, worker_nodes, scheduler_nodes, image, app_version, database_endpoint, redis_endpoint, base_url]
        if any(self._substitution_tokens(value) for value in values):
            return []
        errors = []
        for label, value, minimum in (("web_nodes", web_nodes, 2), ("worker_nodes", worker_nodes, 1), ("scheduler_nodes", scheduler_nodes, 1)):
            try:
                count = int(value)
            except (TypeError, ValueError):
                errors.append(f"{label} must be an integer")
                continue
            if count < minimum:
                errors.append(f"{label} must be at least {minimum}")
        if image in {"", "local-production-smoke", "latest"}:
            errors.append("image must identify a target release image")
        if not app_version:
            errors.append("app_version is required")
        for label, value in (("database_endpoint", database_endpoint), ("redis_endpoint", redis_endpoint)):
            parsed = urlparse(value)
            host = (parsed.hostname or value).split(":", 1)[0].strip().lower()
            if host in {"", "localhost", "127.0.0.1", "::1", "postgres", "redis"}:
                errors.append(f"{label} must identify a shared target service")
        if urlparse(base_url).scheme != "https":
            errors.append("load_balancer must use https")
        return errors

    def _resolve_path(self, raw_path: str | Path) -> Path:
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / path
        return path

    def _quote(self, path: Path) -> str:
        text = str(path)
        return f'"{text}"' if " " in text else text

    def _write_text(self, payload: dict[str, Any]) -> None:
        self.stdout.write("Target environment evidence plan")
        self.stdout.write(f"- commands: {payload['summary']['command_count']}")
        self.stdout.write(f"- destructive commands: {payload['summary']['destructive_command_count']}")
        for item in payload["commands"]:
            self.stdout.write(f"- {item['phase']}:{item['key']} -> {item['output_file']}")

    def _write_safe_script(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        output_dirs = sorted({
            str(Path(str(item["output_file"])).parent)
            for item in payload["safe_archive_manifest"]
        } | {
            str(Path(str(item["stderr_file"])).parent)
            for item in payload["safe_archive_manifest"]
        })
        lines = [
            "# Generated by plan_target_environment_evidence.",
            "# Contains only safe_to_run_unattended=true archive commands with no substitution tokens.",
            "# Manual approval, final validation, destructive, and substitution-required commands are intentionally excluded.",
            "# Output directories are created before command redirection.",
            "$ErrorActionPreference = 'Stop'",
            "",
        ]
        lines.extend(f"New-Item -ItemType Directory -Force -Path {self._ps_quote(directory)} | Out-Null" for directory in output_dirs)
        if output_dirs:
            lines.append("")
        for item in payload["safe_archive_manifest"]:
            lines.append("$global:LASTEXITCODE = 0")
            lines.append(self._shell_archive_command(item))
            lines.append(self._ps_exit_code_assertion(str(item["key"])))
            lines.append(self._ps_output_assertion(str(item["output_file"])))
            lines.append(self._ps_stderr_assertion(str(item["stderr_file"])))
        lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")

    def _write_safe_shell_script(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        output_dirs = sorted({
            str(Path(str(item["output_file"])).parent)
            for item in payload["safe_archive_manifest"]
        } | {
            str(Path(str(item["stderr_file"])).parent)
            for item in payload["safe_archive_manifest"]
        })
        lines = [
            "#!/usr/bin/env sh",
            "# Generated by plan_target_environment_evidence.",
            "# Contains only safe_to_run_unattended=true archive commands with no substitution tokens.",
            "# Manual approval, final validation, destructive, and substitution-required commands are intentionally excluded.",
            "# Output directories are created before command redirection.",
            "set -eu",
            "",
        ]
        lines.extend(f"mkdir -p {self._sh_quote(directory)}" for directory in output_dirs)
        if output_dirs:
            lines.append("")
        for item in payload["safe_archive_manifest"]:
            lines.append(self._shell_archive_command(item))
            lines.append(self._sh_output_assertion(str(item["output_file"])))
            lines.append(self._sh_stderr_assertion(str(item["stderr_file"])))
        lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")

    def _write_json_file(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _ps_quote(self, value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    def _sh_quote(self, value: str) -> str:
        return "'" + value.replace("'", "'\"'\"'") + "'"

    def _ps_exit_code_assertion(self, command_key: str) -> str:
        return f"if (-not $? -or $LASTEXITCODE -ne 0) {{ throw \"archive command failed: {command_key} exit code $LASTEXITCODE\" }}"

    def _ps_output_assertion(self, output_file: str) -> str:
        quoted = self._ps_quote(output_file)
        return f"if (-not (Test-Path -LiteralPath {quoted}) -or (Get-Item -LiteralPath {quoted}).Length -eq 0) {{ throw \"output archive is missing or empty: {output_file}\" }}"

    def _ps_stderr_assertion(self, stderr_file: str) -> str:
        quoted = self._ps_quote(stderr_file)
        return f"if (-not (Test-Path -LiteralPath {quoted}) -or (Get-Item -LiteralPath {quoted}).Length -ne 0) {{ throw \"stderr archive is missing or not empty: {stderr_file}\" }}"

    def _sh_output_assertion(self, output_file: str) -> str:
        quoted = self._sh_quote(output_file)
        return f"test -s {quoted} || {{ echo 'output archive is missing or empty: {output_file}' >&2; exit 1; }}"

    def _sh_stderr_assertion(self, stderr_file: str) -> str:
        quoted = self._sh_quote(stderr_file)
        return f"test -f {quoted} && test ! -s {quoted} || {{ echo 'stderr archive is missing or not empty: {stderr_file}' >&2; exit 1; }}"

    def _shell_archive_command(self, item: dict[str, Any]) -> str:
        command = str(item.get("command") or "")
        if not command:
            command = self._command_before_redirect(str(item.get("archive_command") or ""))
        output_file = self._sh_quote(str(item["output_file"]))
        stderr_file = self._sh_quote(str(item["stderr_file"]))
        return f"{command} > {output_file} 2> {stderr_file}"

    def _command_before_redirect(self, archive_command: str) -> str:
        marker = " > "
        if marker not in archive_command:
            return archive_command
        return archive_command.split(marker, 1)[0]
