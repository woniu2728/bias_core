from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
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
    help = "在隔离临时目标中演练论坛备份恢复，不覆盖当前数据库、media、static 或 site.json。"

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
            "--database-name-suffix",
            help="PostgreSQL 临时恢复数据库名称后缀。默认使用 UTC 时间戳。",
        )
        parser.add_argument(
            "--keep-temp-database",
            action="store_true",
            help="PostgreSQL 演练后保留临时恢复数据库，便于人工排查。",
        )
        parser.add_argument(
            "--format",
            choices=["text", "json"],
            default="text",
            help="输出格式。json 用于 CI 读取恢复演练结果。",
        )

    def handle(self, *args, **options):
        config_path = self._resolve_path(options["config"])
        config = self._ensure_site_config(config_path)
        backup_dir = self._resolve_path(options["backup_dir"])
        artifacts = self._build_backup_artifacts(config_path, config, backup_dir, options)
        temp_root = Path(tempfile.mkdtemp(prefix="bias-restore-rehearsal-"))
        restore_steps: list[dict[str, object]] = []
        verification: list[dict[str, object]] = []
        errors: list[str] = []
        warnings: list[str] = []
        temp_database = ""
        dropped_temp_database = False

        try:
            missing = [
                artifact for artifact in artifacts.values()
                if artifact["required"] and not artifact["exists"]
            ]
            if missing:
                errors.extend(f"missing {artifact['key']}: {artifact['path']}" for artifact in missing)
            else:
                site_check = self._rehearse_site_config(artifacts["site_config"], temp_root)
                restore_steps.append(site_check["step"])
                verification.append(site_check["verification"])

                database_mode = self._normalize_database_mode(config.database_mode)
                if database_mode == "postgres":
                    database_result = self._rehearse_postgres_database(
                        config,
                        artifacts["database"],
                        suffix=options.get("database_name_suffix"),
                        keep_temp_database=bool(options["keep_temp_database"]),
                    )
                    temp_database = str(database_result["temp_database"])
                    dropped_temp_database = bool(database_result["dropped_temp_database"])
                    restore_steps.extend(database_result["steps"])
                    verification.append(database_result["verification"])
                    errors.extend(str(error) for error in database_result["errors"])
                    warnings.extend(str(warning) for warning in database_result["warnings"])
                else:
                    database_result = self._rehearse_sqlite_database(artifacts["database"], temp_root)
                    restore_steps.append(database_result["step"])
                    verification.append(database_result["verification"])
                    errors.extend(str(error) for error in database_result["errors"])

                for key in ("media", "static_frontend"):
                    directory_result = self._rehearse_directory(artifacts[key], temp_root)
                    restore_steps.append(directory_result["step"])
                    verification.append(directory_result["verification"])
                    errors.extend(str(error) for error in directory_result["errors"])
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

        payload = self._build_payload(
            config_path=config_path,
            backup_dir=backup_dir,
            temp_root=temp_root,
            database_mode=self._normalize_database_mode(config.database_mode),
            temp_database=temp_database,
            dropped_temp_database=dropped_temp_database,
            keep_temp_database=bool(options["keep_temp_database"]),
            artifacts=list(artifacts.values()),
            restore_steps=restore_steps,
            verification=verification,
            errors=errors,
            warnings=warnings,
        )

        if options["format"] == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        self._write_text(payload)
        if not payload["summary"]["ok"]:
            raise CommandError("恢复演练失败：存在不可用的备份产物或临时恢复验证失败")

    def _resolve_path(self, raw_path: str | Path) -> Path:
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / path
        return path

    def _ensure_site_config(self, config_path: Path) -> SiteBootstrapConfig:
        if not config_path.exists():
            raise CommandError(f"站点配置不存在: {config_path}。无法演练恢复。")
        return read_site_config(config_path)

    def _build_backup_artifacts(
        self,
        config_path: Path,
        config: SiteBootstrapConfig,
        backup_dir: Path,
        options: dict,
    ) -> dict[str, dict[str, object]]:
        database_mode = self._normalize_database_mode(config.database_mode)
        if database_mode == "sqlite":
            sqlite_name = Path(config.sqlite_name or "db.sqlite3").name
            database_default = backup_dir / sqlite_name
            database_label = "SQLite 数据库文件备份"
        else:
            database_default = backup_dir / "database.dump"
            database_label = "PostgreSQL dump 备份"

        specs = [
            ("site_config", "站点配置备份", options.get("site_config_backup") or backup_dir / config_path.name, True),
            ("database", database_label, options.get("database_backup") or database_default, True),
            ("media", "media 目录备份", options.get("media_backup") or backup_dir / "media", True),
            (
                "static_frontend",
                "static/frontend 目录备份",
                options.get("static_frontend_backup") or backup_dir / "static" / "frontend",
                True,
            ),
        ]
        artifacts: dict[str, dict[str, object]] = {}
        for key, label, raw_path, required in specs:
            path = self._resolve_path(raw_path)
            artifacts[key] = {
                "key": key,
                "label": label,
                "path": str(path),
                "exists": path.exists(),
                "required": required,
            }
        return artifacts

    def _rehearse_site_config(self, artifact: dict[str, object], temp_root: Path) -> dict[str, object]:
        source = Path(str(artifact["path"]))
        target = temp_root / "site.json"
        shutil.copy2(source, target)
        restored_config = read_site_config(target)
        return {
            "step": {
                "action": "restore_site_config_to_temp_file",
                "artifact_key": "site_config",
                "source": str(source),
                "target": str(target),
                "destructive": False,
                "ok": True,
            },
            "verification": {
                "key": "site_config",
                "ok": True,
                "validated_by": "read_site_config",
                "database_mode": restored_config.database_mode,
                "installed": bool(restored_config.installed),
            },
        }

    def _rehearse_sqlite_database(self, artifact: dict[str, object], temp_root: Path) -> dict[str, object]:
        source = Path(str(artifact["path"]))
        target = temp_root / "database" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        verification: dict[str, object] = {
            "key": "database",
            "ok": False,
            "validated_by": "sqlite_temp_copy",
            "target": str(target),
        }
        errors: list[str] = []
        try:
            connection = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
            try:
                schema_version = connection.execute("PRAGMA schema_version").fetchone()[0]
                table_count = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
                ).fetchone()[0]
            finally:
                connection.close()
            verification.update({"ok": True, "schema_version": schema_version, "table_count": table_count})
        except sqlite3.Error as exc:
            errors.append(f"sqlite restore rehearsal failed: {exc}")
            verification["error"] = str(exc)

        return {
            "step": {
                "action": "restore_sqlite_database_to_temp_file",
                "artifact_key": "database",
                "source": str(source),
                "target": str(target),
                "destructive": False,
                "ok": verification["ok"],
            },
            "verification": verification,
            "errors": errors,
        }

    def _rehearse_postgres_database(
        self,
        config: SiteBootstrapConfig,
        artifact: dict[str, object],
        *,
        suffix: str | None,
        keep_temp_database: bool,
    ) -> dict[str, object]:
        source = Path(str(artifact["path"]))
        temp_database = self._build_temp_database_name(config.db_name, suffix)
        if temp_database == config.db_name:
            return {
                "temp_database": temp_database,
                "dropped_temp_database": False,
                "steps": [],
                "verification": {
                    "key": "database",
                    "ok": False,
                    "validated_by": "pg_restore_temp_database",
                    "error": "temporary database name matches live database",
                },
                "errors": ["temporary database name matches live database"],
                "warnings": [],
            }

        errors: list[str] = []
        warnings: list[str] = []
        steps: list[dict[str, object]] = []
        verification: dict[str, object] = {
            "key": "database",
            "ok": False,
            "validated_by": "pg_restore_temp_database",
            "temp_database": temp_database,
        }
        created = False
        dropped = False
        try:
            create_result = self._run_postgres_command(config, [
                "createdb",
                "--host",
                config.db_host,
                "--port",
                str(config.db_port),
                "--username",
                config.db_user,
                temp_database,
            ])
            steps.append(self._command_step("create_temp_database", create_result))
            if create_result["returncode"] != 0:
                errors.append(str(create_result["message"]))
                verification["error"] = create_result["message"]
            else:
                created = True

                restore_result = self._run_postgres_command(config, [
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
                    temp_database,
                    str(source),
                ])
                restore_step = self._command_step("restore_dump_to_temp_database", restore_result)
                if restore_result["returncode"] != 0:
                    if self._is_tolerable_pg_restore_transaction_timeout(str(restore_result["message"])):
                        warnings.append(str(restore_result["message"]))
                        restore_step["ok"] = True
                        restore_step["tolerated"] = True
                        restore_step["warning"] = restore_result["message"]
                    else:
                        errors.append(str(restore_result["message"]))
                        verification["error"] = restore_result["message"]
                steps.append(restore_step)

                if not errors:
                    verify_result = self._run_postgres_command(config, [
                        "psql",
                        "--host",
                        config.db_host,
                        "--port",
                        str(config.db_port),
                        "--username",
                        config.db_user,
                        "--dbname",
                        temp_database,
                        "--tuples-only",
                        "--no-align",
                        "--command",
                        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';",
                    ])
                    steps.append(self._command_step("verify_temp_database", verify_result))
                    if verify_result["returncode"] != 0:
                        errors.append(str(verify_result["message"]))
                        verification["error"] = verify_result["message"]
                    else:
                        verification.update({
                            "ok": True,
                            "table_count": self._parse_int(verify_result["stdout"]),
                            "query": "information_schema.tables public count",
                        })
        finally:
            if created and not keep_temp_database:
                drop_result = self._run_postgres_command(config, [
                    "dropdb",
                    "--if-exists",
                    "--host",
                    config.db_host,
                    "--port",
                    str(config.db_port),
                    "--username",
                    config.db_user,
                    temp_database,
                ])
                steps.append(self._command_step("drop_temp_database", drop_result))
                dropped = drop_result["returncode"] == 0
                if drop_result["returncode"] != 0:
                    errors.append(str(drop_result["message"]))
                    verification["ok"] = False
                    verification["cleanup_error"] = drop_result["message"]

        return {
            "temp_database": temp_database,
            "dropped_temp_database": dropped,
            "steps": steps,
            "verification": verification,
            "errors": errors,
            "warnings": warnings,
        }

    def _rehearse_directory(self, artifact: dict[str, object], temp_root: Path) -> dict[str, object]:
        source = Path(str(artifact["path"]))
        target = temp_root / str(artifact["key"])
        verification: dict[str, object] = {
            "key": artifact["key"],
            "ok": False,
            "validated_by": "copytree_to_temp_directory",
            "target": str(target),
        }
        errors: list[str] = []
        try:
            if not source.is_dir():
                raise ValueError("backup path is not a directory")
            shutil.copytree(source, target)
            files = [item for item in target.rglob("*") if item.is_file()]
            total_bytes = sum(item.stat().st_size for item in files)
            verification.update({"ok": True, "file_count": len(files), "total_bytes": total_bytes})
        except (OSError, ValueError) as exc:
            errors.append(f"{artifact['key']} restore rehearsal failed: {exc}")
            verification["error"] = str(exc)

        return {
            "step": {
                "action": f"restore_{artifact['key']}_to_temp_directory",
                "artifact_key": artifact["key"],
                "source": str(source),
                "target": str(target),
                "destructive": False,
                "ok": verification["ok"],
            },
            "verification": verification,
            "errors": errors,
        }

    def _run_postgres_command(self, config: SiteBootstrapConfig, command: list[str]) -> dict[str, object]:
        env = os.environ.copy()
        if config.db_password:
            env["PGPASSWORD"] = config.db_password
        try:
            completed = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:
            return {
                "command": command,
                "returncode": 127,
                "stdout": "",
                "stderr": "",
                "message": f"{command[0]} not found",
            }
        message = (completed.stderr or completed.stdout or "").strip()
        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "message": message,
        }

    def _command_step(self, action: str, result: dict[str, object]) -> dict[str, object]:
        return {
            "action": action,
            "command": result["command"],
            "returncode": result["returncode"],
            "ok": result["returncode"] == 0,
            "message": result["message"],
            "destructive": False,
        }

    def _build_payload(
        self,
        *,
        config_path: Path,
        backup_dir: Path,
        temp_root: Path,
        database_mode: str,
        temp_database: str,
        dropped_temp_database: bool,
        keep_temp_database: bool,
        artifacts: list[dict[str, object]],
        restore_steps: list[dict[str, object]],
        verification: list[dict[str, object]],
        errors: list[str],
        warnings: list[str],
    ) -> dict[str, object]:
        ok = not errors and all(item.get("ok") for item in verification)
        return {
            "config_path": str(config_path),
            "backup_dir": str(backup_dir),
            "database_mode": database_mode,
            "temp_root": str(temp_root),
            "temp_database": temp_database,
            "backup_artifacts": artifacts,
            "restore_steps": restore_steps,
            "verification": verification,
            "errors": errors,
            "warnings": warnings,
            "summary": {
                "ok": ok,
                "error_count": len(errors),
                "warning_count": len(warnings),
                "artifact_count": len(artifacts),
                "verification_count": len(verification),
                "restore_step_count": len(restore_steps),
                "executes_live_restore": False,
                "uses_isolated_restore_targets": True,
                "keep_temp_database": keep_temp_database,
                "dropped_temp_database": dropped_temp_database,
            },
        }

    def _write_text(self, payload: dict[str, object]) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING("Bias 隔离恢复演练"))
        self.stdout.write(f"站点配置: {payload['config_path']}")
        self.stdout.write(f"备份目录: {payload['backup_dir']}")
        self.stdout.write(f"数据库模式: {payload['database_mode']}")
        if payload["temp_database"]:
            self.stdout.write(f"临时数据库: {payload['temp_database']}")
        for item in payload["verification"]:
            status = "ok" if item["ok"] else "failed"
            self.stdout.write(f"- {item['key']}: {status}")
        if payload["summary"]["ok"]:
            self.stdout.write(self.style.SUCCESS("[OK] 隔离恢复演练通过，未覆盖当前运行数据"))
        else:
            self.stdout.write(self.style.ERROR("[ERROR] 隔离恢复演练失败，未覆盖当前运行数据"))

    def _build_temp_database_name(self, live_name: str, suffix: str | None) -> str:
        raw_suffix = suffix or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        safe_suffix = re.sub(r"[^a-zA-Z0-9_]+", "_", raw_suffix).strip("_") or "restore_smoke"
        base = re.sub(r"[^a-zA-Z0-9_]+", "_", live_name).strip("_") or "bias"
        name = f"{base}_restore_smoke_{safe_suffix}"
        return name[:63]

    def _parse_int(self, value: object) -> int | None:
        try:
            return int(str(value).strip().splitlines()[-1])
        except (ValueError, IndexError):
            return None

    def _is_tolerable_pg_restore_transaction_timeout(self, message: str) -> bool:
        return (
            'unrecognized configuration parameter "transaction_timeout"' in message
            and "pg_restore: warning: errors ignored on restore: 1" in message
        )

    def _normalize_database_mode(self, value: str) -> str:
        return "sqlite" if (value or "sqlite").strip().lower().startswith("sqlite") else "postgres"
