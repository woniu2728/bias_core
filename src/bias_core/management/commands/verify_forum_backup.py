from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management import BaseCommand, CommandError
from django.core.management.base import CommandParser

from bias_core.conf.bootstrap import (
    DEFAULT_SITE_CONFIG_PATH,
    read_site_config,
)


class Command(BaseCommand):
    help = "验证论坛备份产物是否存在且可用于后续恢复演练。"

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
            "--format",
            choices=["text", "json"],
            default="text",
            help="输出格式。json 用于 CI 读取备份验证结果。",
        )

    def handle(self, *args, **options):
        config_path = self._resolve_path(options["config"])
        config = self._ensure_site_config(config_path)
        backup_dir = self._resolve_path(options["backup_dir"])
        checks = self._build_checks(config_path, config, backup_dir, options)
        payload = self._build_payload(config_path=config_path, backup_dir=backup_dir, checks=checks)

        if options["format"] == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        self._write_text(payload)
        if not payload["summary"]["ok"]:
            raise CommandError("备份验证失败：存在不可用的备份产物")

    def _resolve_path(self, raw_path: str | Path) -> Path:
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / path
        return path

    def _ensure_site_config(self, config_path: Path):
        if not config_path.exists():
            raise CommandError(f"站点配置不存在: {config_path}。无法验证备份。")
        return read_site_config(config_path)

    def _build_checks(self, config_path: Path, config, backup_dir: Path, options: dict) -> list[dict[str, object]]:
        database_mode = self._normalize_database_mode(config.database_mode)
        if database_mode == "sqlite":
            sqlite_name = Path(config.sqlite_name or "db.sqlite3").name
            database_backup = self._resolve_path(options.get("database_backup") or backup_dir / sqlite_name)
        else:
            database_backup = self._resolve_path(options.get("database_backup") or backup_dir / "database.dump")

        checks = [
            self._check_site_config(
                self._resolve_path(options.get("site_config_backup") or backup_dir / config_path.name)
            ),
            self._check_database_backup(database_backup, database_mode=database_mode),
            self._check_directory(
                key="media",
                label="media 目录备份",
                path=self._resolve_path(options.get("media_backup") or backup_dir / "media"),
            ),
            self._check_directory(
                key="static_frontend",
                label="static/frontend 目录备份",
                path=self._resolve_path(options.get("static_frontend_backup") or backup_dir / "static" / "frontend"),
            ),
        ]
        return checks

    def _check_site_config(self, path: Path) -> dict[str, object]:
        result = self._base_check("site_config", "站点配置备份", path)
        if not result["ok"]:
            return result
        try:
            backup_config = read_site_config(path)
        except Exception as exc:
            return {**result, "ok": False, "error": f"site config parse failed: {exc}"}
        return {
            **result,
            "installed": bool(backup_config.installed),
            "database_mode": backup_config.database_mode,
            "site_domains": list(backup_config.site_domains),
        }

    def _check_database_backup(self, path: Path, *, database_mode: str) -> dict[str, object]:
        label = "SQLite 数据库文件备份" if database_mode == "sqlite" else "PostgreSQL dump 备份"
        result = self._base_check("database", label, path)
        result["database_mode"] = database_mode
        if not result["ok"]:
            return result

        if database_mode == "sqlite":
            try:
                connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                try:
                    connection.execute("PRAGMA schema_version").fetchone()
                finally:
                    connection.close()
            except sqlite3.Error as exc:
                return {**result, "ok": False, "error": f"sqlite backup open failed: {exc}"}
            return {**result, "validated_by": "sqlite_open"}

        command = ["pg_restore", "--list", str(path)]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:
            return {**result, "ok": False, "error": "pg_restore not found", "command": command}
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "pg_restore --list failed").strip()
            return {**result, "ok": False, "error": message, "command": command}
        entries = [line for line in completed.stdout.splitlines() if line.strip() and not line.startswith(";")]
        return {**result, "validated_by": "pg_restore_list", "entry_count": len(entries), "command": command}

    def _check_directory(self, *, key: str, label: str, path: Path) -> dict[str, object]:
        result = self._base_check(key, label, path)
        if not result["ok"]:
            return result
        if not path.is_dir():
            return {**result, "ok": False, "error": "backup path is not a directory"}
        files = [item for item in path.rglob("*") if item.is_file()]
        total_bytes = sum(item.stat().st_size for item in files)
        return {**result, "file_count": len(files), "total_bytes": total_bytes}

    def _base_check(self, key: str, label: str, path: Path) -> dict[str, object]:
        exists = path.exists()
        return {
            "key": key,
            "label": label,
            "path": str(path),
            "exists": exists,
            "ok": exists,
            "size_bytes": path.stat().st_size if exists and path.is_file() else 0,
        }

    def _build_payload(self, *, config_path: Path, backup_dir: Path, checks: list[dict[str, object]]) -> dict[str, object]:
        error_count = sum(1 for check in checks if not check["ok"])
        return {
            "config_path": str(config_path),
            "backup_dir": str(backup_dir),
            "checks": checks,
            "summary": {
                "ok": error_count == 0,
                "error_count": error_count,
                "warning_count": 0,
                "check_count": len(checks),
            },
        }

    def _write_text(self, payload: dict[str, object]) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING("Bias 备份验证"))
        self.stdout.write(f"站点配置: {payload['config_path']}")
        self.stdout.write(f"备份目录: {payload['backup_dir']}")
        for check in payload["checks"]:
            status = "ok" if check["ok"] else "failed"
            self.stdout.write(f"- {check['label']}: {status} ({check['path']})")
        if payload["summary"]["ok"]:
            self.stdout.write(self.style.SUCCESS("[OK] 备份验证通过"))
        else:
            self.stdout.write(self.style.ERROR("[ERROR] 备份验证失败"))

    def _normalize_database_mode(self, value: str) -> str:
        return "sqlite" if (value or "sqlite").strip().lower().startswith("sqlite") else "postgres"
