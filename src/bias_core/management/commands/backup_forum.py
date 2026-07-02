from __future__ import annotations

import json
import shutil
import subprocess
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
    help = "创建论坛升级前备份：site.json、数据库、media 和 static/frontend。"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--config",
            default=str(DEFAULT_SITE_CONFIG_PATH),
            help="当前站点配置文件路径，默认读取 instance/site.json",
        )
        parser.add_argument(
            "--backup-dir",
            help="备份目录。默认 backups/<UTC timestamp>。",
        )
        parser.add_argument("--skip-media", action="store_true", help="跳过 media 目录备份")
        parser.add_argument("--skip-static-frontend", action="store_true", help="跳过 static/frontend 目录备份")
        parser.add_argument("--skip-database", action="store_true", help="跳过数据库备份")
        parser.add_argument("--overwrite", action="store_true", help="允许覆盖已存在的备份文件或目录")
        parser.add_argument("--dry-run", action="store_true", help="只输出备份计划，不写入任何备份产物")
        parser.add_argument(
            "--format",
            choices=["text", "json"],
            default="text",
            help="输出格式。json 用于 CI 读取备份计划和结果。",
        )

    def handle(self, *args, **options):
        config_path = self._resolve_path(options["config"])
        config = self._ensure_site_config(config_path)
        backup_dir = self._resolve_backup_dir(options.get("backup_dir"))
        artifacts = self._build_artifacts(config_path, config, backup_dir, options)
        dry_run = bool(options["dry_run"])

        if dry_run:
            payload = self._build_payload(
                config_path=config_path,
                backup_dir=backup_dir,
                database_mode=self._normalize_database_mode(config.database_mode),
                artifacts=artifacts,
                dry_run=True,
            )
            self._write_payload(payload, output_format=options["format"])
            return

        self._ensure_targets_available(artifacts, overwrite=bool(options["overwrite"]))
        backup_dir.mkdir(parents=True, exist_ok=True)
        for artifact in artifacts:
            self._create_artifact(artifact, config)

        refreshed = self._build_artifacts(config_path, config, backup_dir, options)
        payload = self._build_payload(
            config_path=config_path,
            backup_dir=backup_dir,
            database_mode=self._normalize_database_mode(config.database_mode),
            artifacts=refreshed,
            dry_run=False,
        )
        self._write_payload(payload, output_format=options["format"])
        if not payload["summary"]["ok"]:
            raise CommandError("备份完成后仍有必需产物缺失")

    def _resolve_path(self, raw_path: str | Path) -> Path:
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / path
        return path

    def _resolve_backup_dir(self, raw_path: str | None) -> Path:
        if raw_path:
            return self._resolve_path(raw_path)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return Path(settings.BASE_DIR) / "backups" / stamp

    def _ensure_site_config(self, config_path: Path) -> SiteBootstrapConfig:
        if not config_path.exists():
            raise CommandError(f"站点配置不存在: {config_path}。无法创建备份。")
        return read_site_config(config_path)

    def _build_artifacts(
        self,
        config_path: Path,
        config: SiteBootstrapConfig,
        backup_dir: Path,
        options: dict,
    ) -> list[dict[str, object]]:
        artifacts: list[dict[str, object]] = [
            {
                "key": "site_config",
                "label": "站点配置备份",
                "source": str(config_path),
                "path": str(backup_dir / config_path.name),
                "required": True,
                "exists": (backup_dir / config_path.name).exists(),
                "planned": True,
            }
        ]

        if not options["skip_database"]:
            db_mode = self._normalize_database_mode(config.database_mode)
            if db_mode == "sqlite":
                sqlite_path = self._resolve_path(config.sqlite_name or "db.sqlite3")
                database_path = backup_dir / sqlite_path.name
                label = "SQLite 数据库文件备份"
                source = str(sqlite_path)
            else:
                database_path = backup_dir / "database.dump"
                label = "PostgreSQL dump 备份"
                source = f"{config.db_user}@{config.db_host}:{config.db_port}/{config.db_name}"
            artifacts.append({
                "key": "database",
                "label": label,
                "source": source,
                "path": str(database_path),
                "required": True,
                "exists": database_path.exists(),
                "planned": True,
            })

        if not options["skip_media"]:
            media_source = Path(settings.BASE_DIR) / "media"
            media_path = backup_dir / "media"
            artifacts.append({
                "key": "media",
                "label": "media 目录备份",
                "source": str(media_source),
                "path": str(media_path),
                "required": True,
                "exists": media_path.exists(),
                "planned": True,
            })

        if not options["skip_static_frontend"]:
            static_source = Path(settings.BASE_DIR) / "static" / "frontend"
            static_path = backup_dir / "static" / "frontend"
            artifacts.append({
                "key": "static_frontend",
                "label": "static/frontend 目录备份",
                "source": str(static_source),
                "path": str(static_path),
                "required": True,
                "exists": static_path.exists(),
                "planned": True,
            })

        return artifacts

    def _ensure_targets_available(self, artifacts: list[dict[str, object]], *, overwrite: bool) -> None:
        conflicts = [artifact["path"] for artifact in artifacts if Path(str(artifact["path"])).exists()]
        if conflicts and not overwrite:
            raise CommandError(
                "备份目标已存在，请更换 --backup-dir 或显式传入 --overwrite: "
                + ", ".join(str(path) for path in conflicts)
            )

    def _create_artifact(self, artifact: dict[str, object], config: SiteBootstrapConfig) -> None:
        key = str(artifact["key"])
        source = Path(str(artifact["source"]))
        target = Path(str(artifact["path"]))
        target.parent.mkdir(parents=True, exist_ok=True)

        if key == "database" and self._normalize_database_mode(config.database_mode) == "postgres":
            self._run_pg_dump(config, target)
            return

        if key in {"site_config", "database"}:
            if not source.exists():
                raise CommandError(f"备份源不存在: {source}")
            shutil.copy2(source, target)
            return

        if key in {"media", "static_frontend"}:
            if source.exists():
                shutil.copytree(source, target, dirs_exist_ok=True)
            else:
                target.mkdir(parents=True, exist_ok=True)
            return

        raise CommandError(f"未知备份产物类型: {key}")

    def _run_pg_dump(self, config: SiteBootstrapConfig, target: Path) -> None:
        command = [
            "pg_dump",
            "--format=custom",
            "--file",
            str(target),
            "--host",
            config.db_host,
            "--port",
            str(config.db_port),
            "--username",
            config.db_user,
            config.db_name,
        ]
        env = None
        if config.db_password:
            import os

            env = os.environ.copy()
            env["PGPASSWORD"] = config.db_password

        try:
            result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:
            raise CommandError("未找到 pg_dump，请在执行环境安装 PostgreSQL client") from exc

        if result.returncode != 0:
            message = (result.stderr or result.stdout or "pg_dump failed").strip()
            raise CommandError(f"PostgreSQL 备份失败: {message}")

    def _build_payload(
        self,
        *,
        config_path: Path,
        backup_dir: Path,
        database_mode: str,
        artifacts: list[dict[str, object]],
        dry_run: bool,
    ) -> dict[str, object]:
        missing = [artifact for artifact in artifacts if artifact["required"] and not artifact["exists"]]
        error_count = 0 if dry_run else len(missing)
        return {
            "config_path": str(config_path),
            "backup_dir": str(backup_dir),
            "database_mode": database_mode,
            "backup_artifacts": artifacts,
            "summary": {
                "ok": error_count == 0,
                "error_count": error_count,
                "warning_count": len(missing) if dry_run else 0,
                "dry_run": dry_run,
                "artifact_count": len(artifacts),
                "missing_required_artifact_count": len(missing),
            },
        }

    def _write_payload(self, payload: dict[str, object], *, output_format: str) -> None:
        if output_format == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        self.stdout.write(self.style.MIGRATE_HEADING("Bias 备份计划" if payload["summary"]["dry_run"] else "Bias 备份结果"))
        self.stdout.write(f"站点配置: {payload['config_path']}")
        self.stdout.write(f"备份目录: {payload['backup_dir']}")
        for artifact in payload["backup_artifacts"]:
            status = "ok" if artifact["exists"] else "planned" if payload["summary"]["dry_run"] else "missing"
            self.stdout.write(f"- {artifact['label']}: {status} ({artifact['path']})")
        if payload["summary"]["ok"]:
            self.stdout.write(self.style.SUCCESS("[OK] 备份检查通过"))
        else:
            self.stdout.write(self.style.ERROR("[ERROR] 备份检查失败"))

    def _normalize_database_mode(self, value: str) -> str:
        return "sqlite" if (value or "sqlite").strip().lower().startswith("sqlite") else "postgres"
