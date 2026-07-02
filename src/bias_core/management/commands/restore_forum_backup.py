from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management import BaseCommand, CommandError
from django.core.management.base import CommandParser

from bias_core.conf.bootstrap import (
    DEFAULT_SITE_CONFIG_PATH,
    SiteBootstrapConfig,
    read_site_config,
)


CONFIRM_PHRASE = "restore live forum data"


class Command(BaseCommand):
    help = "从备份恢复论坛 live 数据。默认拒绝执行，必须显式确认覆盖当前数据。"

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
        parser.add_argument("--skip-database", action="store_true", help="跳过数据库恢复")
        parser.add_argument("--skip-media", action="store_true", help="跳过 media 恢复")
        parser.add_argument("--skip-static-frontend", action="store_true", help="跳过 static/frontend 恢复")
        parser.add_argument("--skip-site-config", action="store_true", help="跳过 site.json 恢复")
        parser.add_argument("--dry-run", action="store_true", help="只输出恢复计划，不写入 live 数据")
        parser.add_argument(
            "--i-understand-this-overwrites-live-data",
            action="store_true",
            help="确认本命令会覆盖 live 数据。非 dry-run 必须传入。",
        )
        parser.add_argument(
            "--confirm-phrase",
            default="",
            help=f"二次确认短语。非 dry-run 必须等于 {CONFIRM_PHRASE!r}。",
        )
        parser.add_argument("--format", choices=("text", "json"), default="text")

    def handle(self, *args, **options):
        config_path = self._resolve_path(options["config"])
        config = self._ensure_site_config(config_path)
        backup_dir = self._resolve_path(options["backup_dir"])
        artifacts = self._build_artifacts(config_path, config, backup_dir, options)
        dry_run = bool(options["dry_run"])
        errors: list[str] = []
        restore_steps: list[dict[str, object]] = []
        verification: list[dict[str, object]] = []

        missing = [artifact for artifact in artifacts if artifact["required"] and not artifact["exists"]]
        errors.extend(f"missing {artifact['key']}: {artifact['path']}" for artifact in missing)

        if not dry_run:
            self._validate_live_restore_confirmation(options)
            if not errors:
                for artifact in artifacts:
                    if artifact["planned"]:
                        restore_steps.append(self._restore_artifact(artifact, config))
                verification = self._verify_restored_artifacts(artifacts, config, config_path)

        payload = self._build_payload(
            config_path=config_path,
            backup_dir=backup_dir,
            config=config,
            dry_run=dry_run,
            artifacts=artifacts,
            restore_steps=restore_steps if restore_steps else self._planned_steps(artifacts, config),
            verification=verification,
            errors=errors,
            confirmed=bool(options["i_understand_this_overwrites_live_data"]),
        )

        if options["format"] == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            self._write_text(payload)

        if not payload["summary"]["ok"]:
            raise CommandError("live 恢复未通过：存在缺失备份、确认不足或恢复失败")

    def _resolve_path(self, raw_path: str | Path) -> Path:
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / path
        return path

    def _ensure_site_config(self, config_path: Path) -> SiteBootstrapConfig:
        if not config_path.exists():
            raise CommandError(f"站点配置不存在: {config_path}。无法恢复备份。")
        return read_site_config(config_path)

    def _build_artifacts(
        self,
        config_path: Path,
        config: SiteBootstrapConfig,
        backup_dir: Path,
        options: dict,
    ) -> list[dict[str, object]]:
        database_mode = self._normalize_database_mode(config.database_mode)
        sqlite_target = self._resolve_path(config.sqlite_name or "db.sqlite3")
        database_backup = (
            backup_dir / sqlite_target.name
            if database_mode == "sqlite"
            else backup_dir / "database.dump"
        )
        specs = [
            (
                "database",
                "数据库备份",
                options.get("database_backup") or database_backup,
                sqlite_target if database_mode == "sqlite" else config.db_name,
                not options["skip_database"],
                True,
            ),
            (
                "media",
                "media 目录备份",
                options.get("media_backup") or backup_dir / "media",
                Path(settings.BASE_DIR) / "media",
                not options["skip_media"],
                True,
            ),
            (
                "static_frontend",
                "static/frontend 目录备份",
                options.get("static_frontend_backup") or backup_dir / "static" / "frontend",
                Path(settings.BASE_DIR) / "static" / "frontend",
                not options["skip_static_frontend"],
                True,
            ),
            (
                "site_config",
                "站点配置备份",
                options.get("site_config_backup") or backup_dir / config_path.name,
                config_path,
                not options["skip_site_config"],
                True,
            ),
        ]
        artifacts: list[dict[str, object]] = []
        for key, label, raw_source, target, planned, required in specs:
            source = self._resolve_path(raw_source)
            artifacts.append({
                "key": key,
                "label": label,
                "path": str(source),
                "target": str(target),
                "exists": source.exists(),
                "required": required and planned,
                "planned": planned,
            })
        return artifacts

    def _validate_live_restore_confirmation(self, options: dict) -> None:
        if not options["i_understand_this_overwrites_live_data"]:
            raise CommandError("非 dry-run 恢复必须传入 --i-understand-this-overwrites-live-data")
        if str(options.get("confirm_phrase") or "") != CONFIRM_PHRASE:
            raise CommandError(f"非 dry-run 恢复必须传入 --confirm-phrase {CONFIRM_PHRASE!r}")

    def _restore_artifact(self, artifact: dict[str, object], config: SiteBootstrapConfig) -> dict[str, object]:
        key = str(artifact["key"])
        if key == "database":
            return self._restore_database(artifact, config)
        if key in {"media", "static_frontend"}:
            return self._restore_directory(artifact)
        if key == "site_config":
            return self._restore_file(artifact)
        raise CommandError(f"未知恢复产物类型: {key}")

    def _restore_database(self, artifact: dict[str, object], config: SiteBootstrapConfig) -> dict[str, object]:
        if self._normalize_database_mode(config.database_mode) == "sqlite":
            return self._restore_sqlite_database(artifact)
        return self._restore_postgres_database(artifact, config)

    def _restore_sqlite_database(self, artifact: dict[str, object]) -> dict[str, object]:
        source = Path(str(artifact["path"]))
        target = Path(str(artifact["target"]))
        try:
            connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
            connection.execute("PRAGMA schema_version").fetchone()
            connection.close()
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        except (OSError, sqlite3.Error) as exc:
            raise CommandError(f"SQLite 恢复失败: {exc}") from exc
        return self._step("restore_sqlite_database", artifact, ok=True)

    def _restore_postgres_database(self, artifact: dict[str, object], config: SiteBootstrapConfig) -> dict[str, object]:
        command = [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--host",
            config.db_host,
            "--port",
            str(config.db_port),
            "--username",
            config.db_user,
            "--dbname",
            config.db_name,
            str(artifact["path"]),
        ]
        env = os.environ.copy()
        if config.db_password:
            env["PGPASSWORD"] = config.db_password
        try:
            completed = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:
            raise CommandError("未找到 pg_restore，请在执行环境安装 PostgreSQL client") from exc
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "pg_restore failed").strip()
            raise CommandError(f"PostgreSQL live 恢复失败: {message}")
        step = self._step("restore_postgres_database", artifact, ok=True)
        step["command"] = command
        return step

    def _restore_directory(self, artifact: dict[str, object]) -> dict[str, object]:
        source = Path(str(artifact["path"]))
        target = Path(str(artifact["target"]))
        if not source.is_dir():
            raise CommandError(f"目录备份不存在或不是目录: {source}")
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
        files = [item for item in target.rglob("*") if item.is_file()]
        step = self._step(f"restore_{artifact['key']}", artifact, ok=True)
        step["file_count"] = len(files)
        step["total_bytes"] = sum(item.stat().st_size for item in files)
        return step

    def _restore_file(self, artifact: dict[str, object]) -> dict[str, object]:
        source = Path(str(artifact["path"]))
        target = Path(str(artifact["target"]))
        if not source.is_file():
            raise CommandError(f"文件备份不存在: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return self._step("restore_site_config", artifact, ok=True)

    def _planned_steps(self, artifacts: list[dict[str, object]], config: SiteBootstrapConfig) -> list[dict[str, object]]:
        steps: list[dict[str, object]] = []
        for artifact in artifacts:
            if not artifact["planned"]:
                continue
            action = {
                "database": "restore_postgres_database"
                if self._normalize_database_mode(config.database_mode) == "postgres"
                else "restore_sqlite_database",
                "media": "restore_media",
                "static_frontend": "restore_static_frontend",
                "site_config": "restore_site_config",
            }[str(artifact["key"])]
            steps.append(self._step(action, artifact, ok=bool(artifact["exists"]), planned_only=True))
        return steps

    def _verify_restored_artifacts(
        self,
        artifacts: list[dict[str, object]],
        config: SiteBootstrapConfig,
        config_path: Path,
    ) -> list[dict[str, object]]:
        verification = []
        planned_keys = {str(artifact["key"]) for artifact in artifacts if artifact["planned"]}
        if "site_config" in planned_keys:
            verification.append(self._verify_site_config(config_path))
        if "database" in planned_keys:
            verification.append(self._verify_database(config))
        if "media" in planned_keys:
            verification.append(self._verify_directory(Path(settings.BASE_DIR) / "media", key="media"))
        if "static_frontend" in planned_keys:
            verification.append(self._verify_directory(Path(settings.BASE_DIR) / "static" / "frontend", key="static_frontend"))
        return verification

    def _verify_site_config(self, config_path: Path) -> dict[str, object]:
        try:
            read_site_config(config_path)
        except Exception as exc:
            return {"key": "site_config", "ok": False, "validated_by": "read_site_config", "error": str(exc)}
        return {"key": "site_config", "ok": True, "validated_by": "read_site_config", "path": str(config_path)}

    def _verify_database(self, config: SiteBootstrapConfig) -> dict[str, object]:
        if self._normalize_database_mode(config.database_mode) == "sqlite":
            sqlite_path = self._resolve_path(config.sqlite_name or "db.sqlite3")
            try:
                connection = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
                table_count = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                ).fetchone()[0]
                connection.close()
            except sqlite3.Error as exc:
                return {"key": "database", "ok": False, "validated_by": "sqlite_live_database", "error": str(exc)}
            return {
                "key": "database",
                "ok": True,
                "validated_by": "sqlite_live_database",
                "path": str(sqlite_path),
                "table_count": int(table_count),
            }
        command = [
            "psql",
            "--host",
            config.db_host,
            "--port",
            str(config.db_port),
            "--username",
            config.db_user,
            "--dbname",
            config.db_name,
            "--tuples-only",
            "--no-align",
            "--command",
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';",
        ]
        env = os.environ.copy()
        if config.db_password:
            env["PGPASSWORD"] = config.db_password
        try:
            completed = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:
            raise CommandError("未找到 psql，请在执行环境安装 PostgreSQL client") from exc
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "psql verification failed").strip()
            return {"key": "database", "ok": False, "validated_by": "psql_live_database", "error": message}
        table_count = int((completed.stdout or "0").strip() or "0")
        return {
            "key": "database",
            "ok": table_count > 0,
            "validated_by": "psql_live_database",
            "table_count": table_count,
        }

    def _verify_directory(self, path: Path, *, key: str) -> dict[str, object]:
        if not path.is_dir():
            return {"key": key, "ok": False, "validated_by": "directory_scan", "path": str(path), "error": "not a directory"}
        files = [item for item in path.rglob("*") if item.is_file()]
        return {
            "key": key,
            "ok": True,
            "validated_by": "directory_scan",
            "path": str(path),
            "file_count": len(files),
            "total_bytes": sum(item.stat().st_size for item in files),
        }

    def _step(
        self,
        action: str,
        artifact: dict[str, object],
        *,
        ok: bool,
        planned_only: bool = False,
    ) -> dict[str, object]:
        return {
            "action": action,
            "artifact_key": artifact["key"],
            "source": artifact["path"],
            "target": artifact["target"],
            "destructive": True,
            "planned_only": planned_only,
            "ok": ok,
        }

    def _build_payload(
        self,
        *,
        config_path: Path,
        backup_dir: Path,
        config: SiteBootstrapConfig,
        dry_run: bool,
        artifacts: list[dict[str, object]],
        restore_steps: list[dict[str, object]],
        verification: list[dict[str, object]],
        errors: list[str],
        confirmed: bool,
    ) -> dict[str, object]:
        verification_errors = [
            f"verification failed: {item['key']}"
            for item in verification
            if item.get("ok") is not True
        ]
        errors = [*errors, *verification_errors]
        executed = not dry_run and bool(restore_steps)
        return {
            "config_path": str(config_path),
            "backup_dir": str(backup_dir),
            "database_mode": self._normalize_database_mode(config.database_mode),
            "backup_artifacts": artifacts,
            "restore_steps": restore_steps,
            "verification": verification,
            "errors": errors,
            "summary": {
                "ok": not errors,
                "error_count": len(errors),
                "warning_count": 0,
                "dry_run": dry_run,
                "confirmed_overwrites_live_data": confirmed,
                "executes_live_restore": executed,
                "destructive": True,
                "restore_step_count": len(restore_steps),
                "verification_count": len(verification),
            },
        }

    def _write_text(self, payload: dict[str, object]) -> None:
        title = "Bias live 恢复计划" if payload["summary"]["dry_run"] else "Bias live 恢复结果"
        self.stdout.write(self.style.MIGRATE_HEADING(title))
        self.stdout.write(f"站点配置: {payload['config_path']}")
        self.stdout.write(f"备份目录: {payload['backup_dir']}")
        for step in payload["restore_steps"]:
            status = "ok" if step["ok"] else "missing"
            self.stdout.write(f"- {step['action']}: {status} ({step['source']} -> {step['target']})")
        if payload["summary"]["ok"]:
            self.stdout.write(self.style.SUCCESS("[OK] live 恢复检查通过"))
        else:
            self.stdout.write(self.style.ERROR("[ERROR] live 恢复检查失败"))

    def _normalize_database_mode(self, value: str) -> str:
        return "sqlite" if (value or "sqlite").strip().lower().startswith("sqlite") else "postgres"
