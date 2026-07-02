from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management import BaseCommand, CommandError
from django.core.management.base import CommandParser

from bias_core.conf.bootstrap import (
    DEFAULT_SITE_CONFIG_PATH,
    SiteBootstrapConfig,
    read_site_config,
)


class Command(BaseCommand):
    help = "输出论坛升级失败后的回滚/恢复计划，并检查必需备份产物是否存在。"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--config",
            default=str(DEFAULT_SITE_CONFIG_PATH),
            help="当前站点配置文件路径，默认读取 instance/site.json",
        )
        parser.add_argument(
            "--backup-dir",
            default="backups/latest",
            help="备份目录。相对路径按 BASE_DIR 解析，默认 backups/latest。",
        )
        parser.add_argument("--database-backup", help="数据库备份路径。PostgreSQL 默认 backup-dir/database.dump。")
        parser.add_argument("--media-backup", help="media 备份路径。默认 backup-dir/media。")
        parser.add_argument("--static-frontend-backup", help="static/frontend 备份路径。默认 backup-dir/static/frontend。")
        parser.add_argument("--site-config-backup", help="site.json 备份路径。默认 backup-dir/site.json。")
        parser.add_argument(
            "--require-existing-backups",
            action="store_true",
            help="要求所有必需备份产物存在；缺失时 summary.ok=false，供发布 gate 使用。",
        )
        parser.add_argument(
            "--format",
            choices=["text", "json"],
            default="text",
            help="输出格式。json 用于 CI 读取回滚计划和备份检查结果。",
        )

    def handle(self, *args, **options):
        config_path = self._resolve_path(options["config"])
        config = self._ensure_site_config(config_path)
        backup_dir = self._resolve_path(options["backup_dir"])
        artifacts = self._build_backup_artifacts(config_path, config, backup_dir, options)
        restore_steps = self._build_restore_steps(config, artifacts)
        verification_steps = self._build_verification_steps()
        payload = self._build_payload(
            config_path=config_path,
            config=config,
            backup_dir=backup_dir,
            artifacts=artifacts,
            restore_steps=restore_steps,
            verification_steps=verification_steps,
            require_existing_backups=bool(options["require_existing_backups"]),
        )

        if options["format"] == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        self._write_text_plan(payload)
        if not payload["summary"]["ok"]:
            raise CommandError("回滚计划检查失败：存在缺失的必需备份产物")

    def _resolve_path(self, raw_path: str | Path) -> Path:
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / path
        return path

    def _ensure_site_config(self, config_path: Path) -> SiteBootstrapConfig:
        if not config_path.exists():
            raise CommandError(f"站点配置不存在: {config_path}。无法生成回滚计划。")
        return read_site_config(config_path)

    def _build_backup_artifacts(
        self,
        config_path: Path,
        config: SiteBootstrapConfig,
        backup_dir: Path,
        options: dict,
    ) -> list[dict[str, object]]:
        database_mode = self._normalize_database_mode(config.database_mode)
        if database_mode == "sqlite":
            sqlite_path = Path(config.sqlite_name or "db.sqlite3")
            database_default = backup_dir / sqlite_path.name
            database_target = self._resolve_path(sqlite_path)
            database_restore = f"copy <database_backup> to {database_target}"
            database_label = "SQLite 数据库文件备份"
        else:
            database_default = backup_dir / "database.dump"
            database_restore = (
                f"pg_restore --clean --if-exists --dbname {config.db_name} "
                f"--host {config.db_host} --port {config.db_port} --username {config.db_user} <database_backup>"
            )
            database_label = "PostgreSQL dump 备份"

        media_target = Path(settings.BASE_DIR) / "media"
        static_frontend_target = Path(settings.BASE_DIR) / "static" / "frontend"

        artifact_specs = [
            (
                "site_config",
                "站点配置备份",
                options.get("site_config_backup") or backup_dir / config_path.name,
                config_path,
                f"copy <site_config_backup> to {config_path}",
                True,
            ),
            (
                "database",
                database_label,
                options.get("database_backup") or database_default,
                database_target if database_mode == "sqlite" else None,
                database_restore,
                True,
            ),
            (
                "media",
                "media 目录备份",
                options.get("media_backup") or backup_dir / "media",
                media_target,
                f"Restore media directory from <media_backup> to {media_target}",
                True,
            ),
            (
                "static_frontend",
                "static/frontend 目录备份",
                options.get("static_frontend_backup") or backup_dir / "static" / "frontend",
                static_frontend_target,
                f"Restore static frontend directory from <static_frontend_backup> to {static_frontend_target}",
                True,
            ),
        ]

        artifacts: list[dict[str, object]] = []
        for key, label, raw_source, target, restore_hint, required in artifact_specs:
            source = self._resolve_path(raw_source)
            artifacts.append({
                "key": key,
                "label": label,
                "path": str(source),
                "exists": source.exists(),
                "required": required,
                "restore_target": str(target) if target is not None else "",
                "restore_hint": restore_hint,
            })
        return artifacts

    def _build_restore_steps(self, config: SiteBootstrapConfig, artifacts: list[dict[str, object]]) -> list[dict[str, object]]:
        database_mode = self._normalize_database_mode(config.database_mode)
        database_step = (
            "恢复 PostgreSQL 数据库备份"
            if database_mode == "postgres"
            else "恢复 SQLite 数据库文件"
        )
        return [
            {
                "label": "停止 web、worker、scheduler",
                "action": "stop_services",
                "destructive": False,
                "command_hint": "docker compose stop web worker scheduler",
            },
            {
                "label": database_step,
                "action": "restore_database",
                "destructive": True,
                "artifact_key": "database",
                "command_hint": self._artifact_hint(artifacts, "database"),
            },
            {
                "label": "恢复 media 目录",
                "action": "restore_media",
                "destructive": True,
                "artifact_key": "media",
                "command_hint": self._artifact_hint(artifacts, "media"),
            },
            {
                "label": "恢复 static/frontend 目录",
                "action": "restore_static_frontend",
                "destructive": True,
                "artifact_key": "static_frontend",
                "command_hint": self._artifact_hint(artifacts, "static_frontend"),
            },
            {
                "label": "恢复 instance/site.json",
                "action": "restore_site_config",
                "destructive": True,
                "artifact_key": "site_config",
                "command_hint": self._artifact_hint(artifacts, "site_config"),
            },
            {
                "label": "启动 web、worker、scheduler",
                "action": "start_services",
                "destructive": False,
                "command_hint": "docker compose up -d web worker scheduler",
            },
        ]

    def _build_verification_steps(self) -> list[dict[str, str]]:
        return [
            {"label": "Django 系统检查", "command": "python manage.py check"},
            {"label": "严格健康检查", "command": "curl -f http://127.0.0.1:8000/api/health?strict=1"},
            {
                "label": "HTTP P95 smoke",
                "command": "python manage.py smoke_http_p95 --base-url http://127.0.0.1:8000 --fail-on-threshold --format json",
            },
            {
                "label": "队列 worker smoke",
                "command": "python manage.py smoke_queue_worker --broker-url redis://127.0.0.1:6379/1 --result-backend redis://127.0.0.1:6379/2 --timeout 45 --format json",
            },
        ]

    def _build_payload(
        self,
        *,
        config_path: Path,
        config: SiteBootstrapConfig,
        backup_dir: Path,
        artifacts: list[dict[str, object]],
        restore_steps: list[dict[str, object]],
        verification_steps: list[dict[str, str]],
        require_existing_backups: bool,
    ) -> dict[str, object]:
        missing_required = [
            artifact for artifact in artifacts
            if artifact["required"] and not artifact["exists"]
        ]
        error_count = len(missing_required) if require_existing_backups else 0
        warning_count = len(missing_required) if not require_existing_backups else 0
        return {
            "config_path": str(config_path),
            "backup_dir": str(backup_dir),
            "database_mode": self._normalize_database_mode(config.database_mode),
            "redis_enabled": bool(config.use_redis),
            "backup_artifacts": artifacts,
            "restore_steps": restore_steps,
            "verification_steps": verification_steps,
            "summary": {
                "ok": error_count == 0,
                "error_count": error_count,
                "warning_count": warning_count,
                "require_existing_backups": require_existing_backups,
                "missing_required_artifact_count": len(missing_required),
                "executes_restore": False,
            },
        }

    def _write_text_plan(self, payload: dict[str, object]) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING("Bias 回滚/恢复计划"))
        self.stdout.write(f"站点配置: {payload['config_path']}")
        self.stdout.write(f"备份目录: {payload['backup_dir']}")
        self.stdout.write(f"数据库模式: {payload['database_mode']}")
        self.stdout.write("备份检查:")
        for artifact in payload["backup_artifacts"]:
            status = "ok" if artifact["exists"] else "missing"
            self.stdout.write(f"- {artifact['label']}: {status} ({artifact['path']})")
        self.stdout.write("恢复步骤:")
        for step in payload["restore_steps"]:
            self.stdout.write(f"- {step['label']}: {step['command_hint']}")
        self.stdout.write("恢复后验证:")
        for step in payload["verification_steps"]:
            self.stdout.write(f"- {step['label']}: {step['command']}")
        if payload["summary"]["ok"]:
            self.stdout.write(self.style.SUCCESS("[OK] 回滚计划检查通过，命令未执行任何恢复操作"))
        else:
            self.stdout.write(self.style.ERROR("[ERROR] 存在缺失的必需备份产物，命令未执行任何恢复操作"))

    def _artifact_hint(self, artifacts: list[dict[str, object]], key: str) -> str:
        for artifact in artifacts:
            if artifact["key"] == key:
                return str(artifact["restore_hint"])
        return ""

    def _normalize_database_mode(self, value: str) -> str:
        return "sqlite" if (value or "sqlite").strip().lower().startswith("sqlite") else "postgres"
