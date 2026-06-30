from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
from typing import Any
import zipfile

from bias_core.extensions.paths import extension_distribution_package, extension_python_package


PACKAGE_RESOURCE_DIRS = ("frontend", "locale")


@dataclass(frozen=True)
class ExtensionPackageResourceInspection:
    pyproject_path: Path
    source_files: tuple[str, ...]
    packaged_files: tuple[str, ...]
    missing_files: tuple[str, ...]
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtensionPackageMetadataInspection:
    pyproject_path: Path
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ExtensionPackageMetadataSyncResult:
    pyproject_path: Path
    changed: bool
    updates: tuple[str, ...]
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtensionPackageWheelInspection:
    extension_id: str
    extension_root: Path
    pyproject_path: Path
    wheel_path: Path | None
    built: bool
    install_smoke: bool
    source_files: tuple[str, ...]
    packaged_files: tuple[str, ...]
    discovered_extension_id: str
    discovered_source: str
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ExtensionPackageInstallSmokeInspection:
    extension_ids: tuple[str, ...]
    wheel_paths: tuple[Path, ...]
    discovered_extension_ids: tuple[str, ...]
    discovered_sources: dict[str, str]
    discovered_migration_modules: dict[str, str]
    migration_smoke: bool
    applied_migration_files: dict[str, tuple[str, ...]]
    boot_order: tuple[str, ...]
    errors: tuple[str, ...]


def inspect_extension_package_resources(extension_root: Path) -> ExtensionPackageResourceInspection | None:
    root = Path(extension_root)
    pyproject_path = root / "pyproject.toml"
    if not pyproject_path.exists():
        return None

    try:
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return ExtensionPackageResourceInspection(
            pyproject_path=pyproject_path,
            source_files=tuple(_iter_package_source_files(root)),
            packaged_files=(),
            missing_files=(),
            errors=("invalid_toml",),
        )

    source_files = tuple(_iter_package_source_files(root))
    packaged_files = tuple(_iter_setuptools_data_files(payload))
    packaged_set = set(packaged_files)
    missing_files = tuple(item for item in source_files if item not in packaged_set)
    return ExtensionPackageResourceInspection(
        pyproject_path=pyproject_path,
        source_files=source_files,
        packaged_files=packaged_files,
        missing_files=missing_files,
    )


def inspect_extension_package_metadata(
    extension_root: Path,
    *,
    extension_id: str,
    extension_version: str,
    manifest_dependencies: tuple[str, ...] = (),
    backend_entry: str,
) -> ExtensionPackageMetadataInspection | None:
    root = Path(extension_root)
    pyproject_path = root / "pyproject.toml"
    if not pyproject_path.exists():
        return None

    try:
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return ExtensionPackageMetadataInspection(
            pyproject_path=pyproject_path,
            errors=("pyproject.toml 不是合法 TOML",),
        )

    errors: list[str] = []
    project = payload.get("project", {})
    if not isinstance(project, dict):
        project = {}

    expected_package_name = extension_distribution_package(extension_id)
    actual_package_name = str(project.get("name") or "").strip()
    if actual_package_name != expected_package_name:
        errors.append(f"project.name 应为 {expected_package_name}")
    actual_version = str(project.get("version") or "").strip()
    if actual_version != str(extension_version or "").strip():
        errors.append(f"project.version 应与 extension.json version 一致: {extension_version}")
    dependencies = project.get("dependencies", [])
    if not isinstance(dependencies, list):
        dependencies = []
    if not any(str(item or "").strip().startswith("bias-core") for item in dependencies):
        errors.append("project.dependencies 必须声明 bias-core 依赖")

    entry_points = project.get("entry-points", {})
    if not isinstance(entry_points, dict):
        entry_points = {}
    extension_entry_points = entry_points.get("bias.extensions", {})
    if not isinstance(extension_entry_points, dict):
        extension_entry_points = {}
    expected_entry_key = extension_id.replace("-", "_")
    expected_backend_entry = backend_entry.strip()
    if expected_backend_entry and ":" not in expected_backend_entry:
        expected_backend_entry = f"{expected_backend_entry}:extend"
    actual_backend_entry = str(extension_entry_points.get(expected_entry_key) or "").strip()
    if actual_backend_entry != expected_backend_entry:
        errors.append(f"project.entry-points.bias.extensions.{expected_entry_key} 应为 {expected_backend_entry}")

    package_include = _project_package_find_include(payload)
    expected_include = [f"{extension_python_package(extension_id)}*"]
    if package_include != expected_include:
        errors.append(f"tool.setuptools.packages.find.include 应为 {expected_include}")

    data_files = _project_data_files(payload)
    manifest_target = f"bias_extensions/{extension_id}"
    if data_files.get(manifest_target) != ["extension.json"]:
        errors.append(f"tool.setuptools.data-files.{manifest_target} 应包含 extension.json")

    return ExtensionPackageMetadataInspection(
        pyproject_path=pyproject_path,
        errors=tuple(errors),
    )


def inspect_extension_package_wheel(
    extension_root: Path,
    *,
    extension_id: str,
    extension_version: str,
    backend_entry: str,
    build: bool = False,
    install_smoke: bool = False,
    wheel_dir: Path | None = None,
    build_output_dir: Path | None = None,
    timeout: int = 120,
) -> ExtensionPackageWheelInspection:
    root = Path(extension_root)
    pyproject_path = root / "pyproject.toml"
    source_files = tuple(_iter_package_source_files(root))
    errors: list[str] = []

    if not pyproject_path.exists():
        return ExtensionPackageWheelInspection(
            extension_id=extension_id,
            extension_root=root,
            pyproject_path=pyproject_path,
            wheel_path=None,
            built=False,
            install_smoke=install_smoke,
            source_files=source_files,
            packaged_files=(),
            discovered_extension_id="",
            discovered_source="",
            errors=("pyproject.toml 不存在，无法构建扩展 wheel",),
        )

    if build:
        if build_output_dir is not None:
            output_dir = Path(build_output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            return _build_and_inspect_extension_wheel(
                root,
                output_dir,
                extension_id=extension_id,
                extension_version=extension_version,
                pyproject_path=pyproject_path,
                source_files=source_files,
                backend_entry=backend_entry,
                install_smoke=install_smoke,
                timeout=timeout,
            )
        with tempfile.TemporaryDirectory(prefix=f"bias-wheel-{extension_id}-") as temp_dir:
            return _build_and_inspect_extension_wheel(
                root,
                Path(temp_dir),
                extension_id=extension_id,
                extension_version=extension_version,
                pyproject_path=pyproject_path,
                source_files=source_files,
                backend_entry=backend_entry,
                install_smoke=install_smoke,
                timeout=timeout,
            )

    search_dir = Path(wheel_dir) if wheel_dir is not None else root / "dist"
    wheel_path = _select_extension_wheel(search_dir, extension_id=extension_id, extension_version=extension_version)
    if wheel_path is None:
        return ExtensionPackageWheelInspection(
            extension_id=extension_id,
            extension_root=root,
            pyproject_path=pyproject_path,
            wheel_path=None,
            built=False,
            install_smoke=install_smoke,
            source_files=source_files,
            packaged_files=(),
            discovered_extension_id="",
            discovered_source="",
            errors=(f"未在 {search_dir} 找到匹配的扩展 wheel；请先构建或传 --build",),
        )
    return _inspect_wheel_archive(
        wheel_path,
        extension_id=extension_id,
        extension_root=root,
        pyproject_path=pyproject_path,
        source_files=source_files,
        backend_entry=backend_entry,
        built=False,
        install_smoke=install_smoke,
        timeout=timeout,
    )


def inspect_extension_package_install_set(
    wheel_paths: list[Path] | tuple[Path, ...],
    *,
    expected_extensions: dict[str, str],
    migration_smoke: bool = False,
    timeout: int = 120,
) -> ExtensionPackageInstallSmokeInspection:
    normalized_wheel_paths = tuple(Path(path) for path in wheel_paths)
    expected_extension_ids = tuple(sorted(expected_extensions.keys()))
    if not normalized_wheel_paths:
        return ExtensionPackageInstallSmokeInspection(
            extension_ids=expected_extension_ids,
            wheel_paths=(),
            discovered_extension_ids=(),
            discovered_sources={},
            discovered_migration_modules={},
            migration_smoke=migration_smoke,
            applied_migration_files={},
            boot_order=(),
            errors=("未提供可安装的扩展 wheel",),
        )

    with tempfile.TemporaryDirectory(prefix="bias-install-set-") as temp_dir:
        target_dir = Path(temp_dir)
        install_errors = _install_wheels_to_target(normalized_wheel_paths, target_dir, timeout=timeout)
        if install_errors:
            return ExtensionPackageInstallSmokeInspection(
                extension_ids=expected_extension_ids,
                wheel_paths=normalized_wheel_paths,
                discovered_extension_ids=(),
                discovered_sources={},
                discovered_migration_modules={},
                migration_smoke=migration_smoke,
                applied_migration_files={},
                boot_order=(),
                errors=tuple(install_errors),
            )
        smoke_result = _run_isolated_install_set_smoke(
            target_dir,
            expected_extensions=expected_extensions,
            migration_smoke=migration_smoke,
            timeout=timeout,
        )
    return ExtensionPackageInstallSmokeInspection(
        extension_ids=expected_extension_ids,
        wheel_paths=normalized_wheel_paths,
        discovered_extension_ids=tuple(smoke_result["discovered_extension_ids"]),
        discovered_sources=dict(smoke_result["discovered_sources"]),
        discovered_migration_modules=dict(smoke_result["discovered_migration_modules"]),
        migration_smoke=migration_smoke,
        applied_migration_files={
            str(key): tuple(str(item) for item in value)
            for key, value in dict(smoke_result["applied_migration_files"]).items()
        },
        boot_order=tuple(smoke_result["boot_order"]),
        errors=tuple(smoke_result["errors"]),
    )


def sync_extension_package_metadata(
    extension_root: Path,
    *,
    extension_id: str,
    extension_version: str,
    manifest_dependencies: tuple[str, ...] = (),
    backend_entry: str,
    write: bool = False,
) -> ExtensionPackageMetadataSyncResult:
    root = Path(extension_root)
    pyproject_path = root / "pyproject.toml"
    if not pyproject_path.exists():
        return ExtensionPackageMetadataSyncResult(
            pyproject_path=pyproject_path,
            changed=False,
            updates=(),
            errors=("pyproject.toml 不存在",),
        )

    try:
        source = pyproject_path.read_text(encoding="utf-8")
        payload = tomllib.loads(source)
    except tomllib.TOMLDecodeError:
        return ExtensionPackageMetadataSyncResult(
            pyproject_path=pyproject_path,
            changed=False,
            updates=(),
            errors=("pyproject.toml 不是合法 TOML",),
        )

    normalized, updates = _normalized_package_metadata_payload(
        payload,
        extension_id=extension_id,
        extension_version=extension_version,
        manifest_dependencies=manifest_dependencies,
        backend_entry=backend_entry,
        extension_root=root,
    )
    normalized_source = _dump_pyproject_toml(normalized)
    changed = bool(updates)
    if write and changed:
        _write_text_lf(pyproject_path, normalized_source)
    return ExtensionPackageMetadataSyncResult(
        pyproject_path=pyproject_path,
        changed=changed,
        updates=tuple(updates),
    )


def _build_extension_wheel(root: Path, output_dir: Path, *, timeout: int) -> tuple[str, ...]:
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--no-isolation",
                "--outdir",
                str(output_dir),
            ],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return (f"构建扩展 wheel 超时: {exc}",)
    except OSError as exc:
        return (f"无法启动扩展 wheel 构建: {exc}",)

    if result.returncode == 0:
        return ()
    detail = "\n".join(part.strip() for part in (result.stderr, result.stdout) if part.strip())
    if len(detail) > 2000:
        detail = detail[:2000] + "...[truncated]"
    return (f"构建扩展 wheel 失败: {detail or result.returncode}",)


def _build_and_inspect_extension_wheel(
    root: Path,
    output_dir: Path,
    *,
    extension_id: str,
    extension_version: str,
    pyproject_path: Path,
    source_files: tuple[str, ...],
    backend_entry: str,
    install_smoke: bool,
    timeout: int,
) -> ExtensionPackageWheelInspection:
    build_errors = _build_extension_wheel(root, output_dir, timeout=timeout)
    if build_errors:
        return ExtensionPackageWheelInspection(
            extension_id=extension_id,
            extension_root=root,
            pyproject_path=pyproject_path,
            wheel_path=None,
            built=True,
            install_smoke=install_smoke,
            source_files=source_files,
            packaged_files=(),
            discovered_extension_id="",
            discovered_source="",
            errors=tuple(build_errors),
        )
    wheel_path = _select_extension_wheel(output_dir, extension_id=extension_id, extension_version=extension_version)
    if wheel_path is None:
        return ExtensionPackageWheelInspection(
            extension_id=extension_id,
            extension_root=root,
            pyproject_path=pyproject_path,
            wheel_path=None,
            built=True,
            install_smoke=install_smoke,
            source_files=source_files,
            packaged_files=(),
            discovered_extension_id="",
            discovered_source="",
            errors=("构建完成但未找到匹配的扩展 wheel",),
        )
    return _inspect_wheel_archive(
        wheel_path,
        extension_id=extension_id,
        extension_root=root,
        pyproject_path=pyproject_path,
        source_files=source_files,
        backend_entry=backend_entry,
        built=True,
        install_smoke=install_smoke,
        timeout=timeout,
    )


def _select_extension_wheel(
    wheel_dir: Path,
    *,
    extension_id: str,
    extension_version: str,
) -> Path | None:
    if not wheel_dir.exists():
        return None
    package_prefix = f"{extension_python_package(extension_id)}-"
    version_marker = f"-{extension_version}-"
    candidates = [
        path
        for path in sorted(wheel_dir.glob("*.whl"))
        if path.name.startswith(package_prefix) and version_marker in path.name
    ]
    if candidates:
        return candidates[-1]
    fallback_prefix = extension_python_package(extension_id)
    fallback = [path for path in sorted(wheel_dir.glob("*.whl")) if path.name.startswith(fallback_prefix)]
    return fallback[-1] if fallback else None


def _inspect_wheel_archive(
    wheel_path: Path,
    *,
    extension_id: str,
    extension_root: Path,
    pyproject_path: Path,
    source_files: tuple[str, ...],
    backend_entry: str,
    built: bool,
    install_smoke: bool,
    timeout: int,
) -> ExtensionPackageWheelInspection:
    errors: list[str] = []
    discovered_extension_id = ""
    discovered_source = ""
    try:
        with zipfile.ZipFile(wheel_path) as archive:
            archive_names = tuple(sorted(archive.namelist()))
            archive_set = set(archive_names)
            _validate_wheel_manifest_files(errors, archive_set, extension_id=extension_id, source_files=source_files)
            _validate_wheel_entry_points(errors, archive, archive_names, extension_id=extension_id, backend_entry=backend_entry)
            _validate_wheel_backend_module(errors, archive_set, backend_entry=backend_entry)
        if install_smoke:
            smoke_result = _smoke_test_wheel_installation(
                wheel_path,
                extension_id=extension_id,
                backend_entry=backend_entry,
                timeout=timeout,
            )
            discovered_extension_id = smoke_result["discovered_extension_id"]
            discovered_source = smoke_result["discovered_source"]
            errors.extend(smoke_result["errors"])
    except zipfile.BadZipFile:
        return ExtensionPackageWheelInspection(
            extension_id=extension_id,
            extension_root=extension_root,
            pyproject_path=pyproject_path,
            wheel_path=wheel_path,
            built=built,
            install_smoke=install_smoke,
            source_files=source_files,
            packaged_files=(),
            discovered_extension_id="",
            discovered_source="",
            errors=("扩展 wheel 不是有效 zip 归档",),
        )

    return ExtensionPackageWheelInspection(
        extension_id=extension_id,
        extension_root=extension_root,
        pyproject_path=pyproject_path,
        wheel_path=wheel_path,
        built=built,
        install_smoke=install_smoke,
        source_files=source_files,
        packaged_files=archive_names,
        discovered_extension_id=discovered_extension_id,
        discovered_source=discovered_source,
        errors=tuple(errors),
    )


def _smoke_test_wheel_installation(
    wheel_path: Path,
    *,
    extension_id: str,
    backend_entry: str,
    timeout: int,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"bias-install-{extension_id}-") as temp_dir:
        target_dir = Path(temp_dir)
        install_errors = _install_wheel_to_target(wheel_path, target_dir, timeout=timeout)
        if install_errors:
            return {
                "discovered_extension_id": "",
                "discovered_source": "",
                "errors": list(install_errors),
            }
        return _run_isolated_install_smoke(
            target_dir,
            extension_id=extension_id,
            backend_entry=backend_entry,
            timeout=timeout,
        )


def _run_isolated_install_smoke(
    target_dir: Path,
    *,
    extension_id: str,
    backend_entry: str,
    timeout: int,
) -> dict[str, Any]:
    script = r"""
import importlib
import importlib.util
import json
import sys
from pathlib import Path

core_src = Path(sys.argv[1])
target_dir = Path(sys.argv[2])
extension_id = sys.argv[3]
expected_backend_entry = sys.argv[4]
manifest_path = target_dir / "bias_extensions" / extension_id / "extension.json"
django_app_config = ""
if manifest_path.exists():
    try:
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        manifest_payload = {}
    django_payload = manifest_payload.get("django") if isinstance(manifest_payload.get("django"), dict) else {}
    django_app_config = str(
        manifest_payload.get("django_app_config")
        or django_payload.get("app_config")
        or ""
    ).strip()

sys.path.insert(0, str(core_src))
sys.path.insert(0, str(target_dir))

from django.conf import settings

if not settings.configured:
    settings.configure(
        INSTALLED_APPS=[
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "bias_core",
            *([django_app_config] if django_app_config else []),
        ],
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": ":memory:",
            },
        },
        SECRET_KEY="bias-install-smoke",
        BASE_DIR=str(target_dir),
        USE_TZ=True,
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        BIAS_EXTENSION_PACKAGE_DISCOVERY=False,
    )
import django
django.setup()

from bias_core.extensions.manifest import ExtensionManifestLoader

manifests = ExtensionManifestLoader(
    target_dir / "empty-extensions",
    include_workspace=False,
    include_distributions=True,
    distribution_path=target_dir,
).discover_manifests()
matching = [manifest for manifest in manifests if manifest.id == extension_id]
payload = {
    "discovered_extension_id": "",
    "discovered_source": "",
    "errors": [],
}
if not matching:
    payload["errors"].append(f"安装态发现器未从 wheel 中发现扩展 {extension_id}")
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(0)

manifest = matching[0]
payload["discovered_extension_id"] = manifest.id
payload["discovered_source"] = manifest.source
if manifest.source != "python-package":
    payload["errors"].append(f"安装态扩展来源应为 python-package，实际为 {manifest.source}")
if manifest.backend_entry != expected_backend_entry:
    payload["errors"].append(f"安装态 manifest backend entry 应为 {expected_backend_entry}")
if expected_backend_entry:
    module_name = expected_backend_entry.split(":", 1)[0].strip()
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        payload["errors"].append(f"安装态后端入口不可导入: {expected_backend_entry}: {type(exc).__name__}: {exc}")
    else:
        hook_name = expected_backend_entry.split(":", 1)[1].strip() if ":" in expected_backend_entry else "extend"
        if hook_name and not callable(getattr(module, hook_name, None)):
            payload["errors"].append(f"安装态后端入口缺少可调用 hook: {expected_backend_entry}")
print(json.dumps(payload, ensure_ascii=False))
"""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                script,
                str(_core_source_root()),
                str(target_dir),
                extension_id,
                str(backend_entry or "").strip(),
            ],
            text=True,
            capture_output=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "discovered_extension_id": "",
            "discovered_source": "",
            "errors": [f"安装态隔离 smoke 超时: {exc}"],
        }
    except OSError as exc:
        return {
            "discovered_extension_id": "",
            "discovered_source": "",
            "errors": [f"无法启动安装态隔离 smoke: {exc}"],
        }

    if result.returncode != 0:
        detail = "\n".join(part.strip() for part in (result.stderr, result.stdout) if part.strip())
        if len(detail) > 2000:
            detail = detail[:2000] + "...[truncated]"
        return {
            "discovered_extension_id": "",
            "discovered_source": "",
            "errors": [f"安装态隔离 smoke 失败: {detail or result.returncode}"],
        }
    try:
        payload = json.loads(result.stdout.strip() or "{}")
    except json.JSONDecodeError as exc:
        return {
            "discovered_extension_id": "",
            "discovered_source": "",
            "errors": [f"安装态隔离 smoke 输出不是有效 JSON: {exc}"],
        }
    return {
        "discovered_extension_id": str(payload.get("discovered_extension_id") or ""),
        "discovered_source": str(payload.get("discovered_source") or ""),
        "errors": [str(item) for item in payload.get("errors", []) if str(item)],
    }


def _core_source_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _install_wheel_to_target(wheel_path: Path, target_dir: Path, *, timeout: int) -> tuple[str, ...]:
    return _install_wheels_to_target((wheel_path,), target_dir, timeout=timeout)


def _install_wheels_to_target(wheel_paths: list[Path] | tuple[Path, ...], target_dir: Path, *, timeout: int) -> tuple[str, ...]:
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--disable-pip-version-check",
                "--target",
                str(target_dir),
                *(str(path) for path in wheel_paths),
            ],
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return (f"安装扩展 wheel 超时: {exc}",)
    except OSError as exc:
        return (f"无法启动扩展 wheel 安装: {exc}",)

    if result.returncode == 0:
        return ()
    detail = "\n".join(part.strip() for part in (result.stderr, result.stdout) if part.strip())
    if len(detail) > 2000:
        detail = detail[:2000] + "...[truncated]"
    return (f"安装扩展 wheel 失败: {detail or result.returncode}",)


def _run_isolated_install_set_smoke(
    target_dir: Path,
    *,
    expected_extensions: dict[str, str],
    migration_smoke: bool,
    timeout: int,
) -> dict[str, Any]:
    script = r"""
import importlib
import importlib.util
import json
import sys
from pathlib import Path

core_src = Path(sys.argv[1])
target_dir = Path(sys.argv[2])
expected_extensions = json.loads(sys.argv[3])
migration_smoke = sys.argv[4] == "1"

sys.path.insert(0, str(core_src))
sys.path.insert(0, str(target_dir))

installed_apps = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "bias_core",
]
migration_modules = {}
for extension_id in sorted(expected_extensions):
    manifest_path = target_dir / "bias_extensions" / extension_id / "extension.json"
    if not manifest_path.exists():
        continue
    try:
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        continue
    django_payload = manifest_payload.get("django") if isinstance(manifest_payload.get("django"), dict) else {}
    app_config = str(
        manifest_payload.get("django_app_config")
        or django_payload.get("app_config")
        or ""
    ).strip()
    if app_config and app_config not in installed_apps:
        installed_apps.append(app_config)
    app_label = str(
        manifest_payload.get("django_app_label")
        or django_payload.get("app_label")
        or extension_id.replace("-", "_")
    ).strip()
    migration_module = str(
        manifest_payload.get("django_migration_module")
        or django_payload.get("migration_module")
        or ""
    ).strip()
    if not migration_module:
        module_prefix = app_config.rsplit(".apps.", 1)[0]
        if module_prefix and module_prefix != app_config:
            migration_module = f"{module_prefix}.django_migrations"
    if app_label and migration_module:
        migration_modules[app_label] = migration_module

from django.conf import settings

if not settings.configured:
    settings.configure(
        INSTALLED_APPS=installed_apps,
        MIGRATION_MODULES=migration_modules,
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": str(target_dir / "migration-smoke.sqlite3"),
            },
        },
        SECRET_KEY="bias-install-set-smoke",
        BASE_DIR=str(target_dir),
        USE_TZ=True,
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        BIAS_EXTENSION_PACKAGE_DISCOVERY=False,
    )
import django
django.setup()

from bias_core.extensions.manifest import ExtensionManifestLoader
from bias_core.extensions.manager_dependencies import get_core_satisfied_dependency_ids, resolve_extension_order

manifests = ExtensionManifestLoader(
    target_dir / "empty-extensions",
    include_workspace=False,
    include_distributions=True,
    distribution_path=target_dir,
).discover_manifests()
manifest_by_id = {manifest.id: manifest for manifest in manifests}
payload = {
    "discovered_extension_ids": sorted(manifest_by_id),
    "discovered_sources": {manifest.id: manifest.source for manifest in manifests},
    "discovered_migration_modules": {},
    "applied_migration_files": {},
    "boot_order": [],
    "errors": [],
}
for extension_id, backend_entry in sorted(expected_extensions.items()):
    manifest = manifest_by_id.get(extension_id)
    if manifest is None:
        payload["errors"].append(f"安装态发现器未发现扩展 {extension_id}")
        continue
    if manifest.source != "python-package":
        payload["errors"].append(f"安装态扩展 {extension_id} 来源应为 python-package，实际为 {manifest.source}")
    if str(manifest.backend_entry or "").strip() != str(backend_entry or "").strip():
        payload["errors"].append(f"安装态扩展 {extension_id} backend entry 应为 {backend_entry}")
    migration_module = ""
    app_label = ""
    manifest_path = target_dir / "bias_extensions" / extension_id / "extension.json"
    if manifest_path.exists():
        try:
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest_payload = {}
        django_payload = manifest_payload.get("django") if isinstance(manifest_payload.get("django"), dict) else {}
        app_label = str(
            manifest_payload.get("django_app_label")
            or django_payload.get("app_label")
            or extension_id.replace("-", "_")
        ).strip()
        migration_module = str(
            manifest_payload.get("django_migration_module")
            or django_payload.get("migration_module")
            or ""
        ).strip()
        if not migration_module:
            app_config = str(
                manifest_payload.get("django_app_config")
                or django_payload.get("app_config")
                or ""
            ).strip()
            module_prefix = app_config.rsplit(".apps.", 1)[0]
            if module_prefix and module_prefix != app_config:
                migration_module = f"{module_prefix}.django_migrations"
    if migration_module:
        payload["discovered_migration_modules"][app_label or extension_id.replace("-", "_")] = migration_module
        try:
            migration_spec = importlib.util.find_spec(migration_module)
        except Exception as exc:
            payload["errors"].append(f"安装态迁移模块不可检查: {migration_module}: {type(exc).__name__}: {exc}")
        else:
            if migration_spec is None:
                payload["errors"].append(f"安装态迁移模块不可导入: {migration_module}")
    if backend_entry:
        module_name = backend_entry.split(":", 1)[0].strip()
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            payload["errors"].append(f"安装态后端入口不可导入: {backend_entry}: {type(exc).__name__}: {exc}")
        else:
            hook_name = backend_entry.split(":", 1)[1].strip() if ":" in backend_entry else "extend"
            if hook_name and not callable(getattr(module, hook_name, None)):
                payload["errors"].append(f"安装态后端入口缺少可调用 hook: {backend_entry}")

try:
    from bias_core.extensions.extension_runtime import Extension

    extensions = [Extension.from_manifest(manifest) for manifest in manifests]
    resolved = resolve_extension_order(
        extensions,
        satisfied_dependency_ids=get_core_satisfied_dependency_ids(),
    )
    payload["boot_order"] = list(resolved.get("order") or [])
    missing_dependencies = dict(resolved.get("missing_dependencies") or {})
    circular_dependencies = list(resolved.get("circular_dependencies") or [])
    if missing_dependencies:
        payload["errors"].append(f"安装态依赖缺失: {missing_dependencies}")
    if circular_dependencies:
        payload["errors"].append(f"安装态依赖循环: {circular_dependencies}")
except Exception as exc:
    payload["errors"].append(f"安装态依赖顺序解析失败: {type(exc).__name__}: {exc}")

if migration_smoke and not payload["errors"]:
    try:
        from django.core.management import call_command
        from django.db import connection
        from django.db.migrations.recorder import MigrationRecorder

        call_command("migrate", verbosity=0, interactive=False)
        applied = MigrationRecorder(connection).applied_migrations()
        for app_label in sorted(migration_modules):
            module_name = migration_modules[app_label]
            try:
                module_spec = importlib.util.find_spec(module_name)
            except Exception as exc:
                payload["errors"].append(f"安装态迁移模块不可检查: {module_name}: {type(exc).__name__}: {exc}")
                continue
            if module_spec is None:
                payload["errors"].append(f"安装态迁移模块不可导入: {module_name}")
                continue
            applied_files = sorted(
                f"{migration_name}.py"
                for migration_app_label, migration_name in applied
                if migration_app_label == app_label
            )
            payload["applied_migration_files"][app_label] = applied_files
            if not applied_files:
                try:
                    module = importlib.import_module(module_name)
                    module_paths = [Path(item) for item in getattr(module, "__path__", [])]
                except Exception:
                    module_paths = []
                declared_files = sorted(
                    item.name
                    for module_path in module_paths
                    for item in module_path.glob("*.py")
                    if item.name != "__init__.py"
                )
                if declared_files:
                    payload["errors"].append(f"安装态数据库迁移未应用: {app_label}: {declared_files}")
    except Exception as exc:
        payload["errors"].append(f"安装态数据库迁移 smoke 失败: {type(exc).__name__}: {exc}")

print(json.dumps(payload, ensure_ascii=False))
"""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                script,
                str(_core_source_root()),
                str(target_dir),
                json.dumps(expected_extensions, ensure_ascii=False),
                "1" if migration_smoke else "0",
            ],
            text=True,
            capture_output=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "discovered_extension_ids": [],
            "discovered_sources": {},
            "discovered_migration_modules": {},
            "applied_migration_files": {},
            "boot_order": [],
            "errors": [f"安装态整组 smoke 超时: {exc}"],
        }
    except OSError as exc:
        return {
            "discovered_extension_ids": [],
            "discovered_sources": {},
            "discovered_migration_modules": {},
            "applied_migration_files": {},
            "boot_order": [],
            "errors": [f"无法启动安装态整组 smoke: {exc}"],
        }

    if result.returncode != 0:
        detail = "\n".join(part.strip() for part in (result.stderr, result.stdout) if part.strip())
        if len(detail) > 2000:
            detail = detail[:2000] + "...[truncated]"
        return {
            "discovered_extension_ids": [],
            "discovered_sources": {},
            "discovered_migration_modules": {},
            "applied_migration_files": {},
            "boot_order": [],
            "errors": [f"安装态整组 smoke 失败: {detail or result.returncode}"],
        }
    try:
        payload = json.loads(result.stdout.strip() or "{}")
    except json.JSONDecodeError as exc:
        return {
            "discovered_extension_ids": [],
            "discovered_sources": {},
            "discovered_migration_modules": {},
            "applied_migration_files": {},
            "boot_order": [],
            "errors": [f"安装态整组 smoke 输出不是有效 JSON: {exc}"],
        }
    return {
        "discovered_extension_ids": [str(item) for item in payload.get("discovered_extension_ids", []) if str(item)],
        "discovered_sources": {
            str(key): str(value)
            for key, value in dict(payload.get("discovered_sources") or {}).items()
        },
        "discovered_migration_modules": {
            str(key): str(value)
            for key, value in dict(payload.get("discovered_migration_modules") or {}).items()
        },
        "applied_migration_files": {
            str(key): [str(item) for item in value if str(item)]
            for key, value in dict(payload.get("applied_migration_files") or {}).items()
        },
        "boot_order": [str(item) for item in payload.get("boot_order", []) if str(item)],
        "errors": [str(item) for item in payload.get("errors", []) if str(item)],
    }


def _validate_wheel_manifest_files(
    errors: list[str],
    archive_files: set[str],
    *,
    extension_id: str,
    source_files: tuple[str, ...],
) -> None:
    manifest_suffix = f"/bias_extensions/{extension_id}/extension.json"
    if not _archive_contains_path_or_suffix(archive_files, f"bias_extensions/{extension_id}/extension.json", manifest_suffix):
        errors.append(f"wheel 缺少 bias_extensions/{extension_id}/extension.json")
    for source_file in source_files:
        expected = f"bias_extensions/{extension_id}/{source_file}"
        expected_suffix = f"/{expected}"
        if not _archive_contains_path_or_suffix(archive_files, expected, expected_suffix):
            errors.append(f"wheel 缺少扩展资源 {source_file}")


def _validate_wheel_entry_points(
    errors: list[str],
    archive: zipfile.ZipFile,
    archive_names: tuple[str, ...],
    *,
    extension_id: str,
    backend_entry: str,
) -> None:
    expected_backend_entry = str(backend_entry or "").strip()
    if expected_backend_entry and ":" not in expected_backend_entry:
        expected_backend_entry = f"{expected_backend_entry}:extend"
    expected_key = extension_id.replace("-", "_")
    entry_point_files = [name for name in archive_names if name.endswith(".dist-info/entry_points.txt")]
    if not entry_point_files:
        errors.append("wheel 缺少 entry_points.txt")
        return
    payload = "\n".join(archive.read(name).decode("utf-8", errors="replace") for name in entry_point_files)
    if "[bias.extensions]" not in payload:
        errors.append("wheel entry_points.txt 缺少 [bias.extensions]")
        return
    expected_line = f"{expected_key} = {expected_backend_entry}"
    if expected_backend_entry and expected_line not in payload:
        errors.append(f"wheel entry point 应包含 {expected_line}")


def _validate_wheel_backend_module(errors: list[str], archive_files: set[str], *, backend_entry: str) -> None:
    module_name = str(backend_entry or "").strip().split(":", 1)[0].strip()
    if not module_name:
        return
    module_path = module_name.replace(".", "/")
    if f"{module_path}.py" in archive_files or f"{module_path}/__init__.py" in archive_files:
        return
    errors.append(f"wheel 缺少后端入口模块 {module_name}")


def _archive_contains_path_or_suffix(archive_files: set[str], path: str, suffix: str) -> bool:
    return path in archive_files or any(item.endswith(suffix) for item in archive_files)


def _iter_package_source_files(root: Path) -> tuple[str, ...]:
    files: list[str] = []
    for directory_name in PACKAGE_RESOURCE_DIRS:
        directory = root / directory_name
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            relative_path = path.relative_to(root)
            if path.is_file() and not _is_ignored_package_resource(relative_path):
                files.append(relative_path.as_posix())
    return tuple(files)


def _is_ignored_package_resource(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)


def _iter_setuptools_data_files(payload: dict) -> tuple[str, ...]:
    data_files = _project_data_files(payload)

    files: list[str] = []
    for items in data_files.values():
        if not isinstance(items, list):
            continue
        for item in items:
            normalized = str(item or "").strip().replace("\\", "/")
            if normalized:
                files.append(normalized)
    return tuple(sorted(set(files)))


def _project_data_files(payload: dict) -> dict:
    data_files = (
        payload.get("tool", {})
        .get("setuptools", {})
        .get("data-files", {})
    )
    return data_files if isinstance(data_files, dict) else {}


def _project_package_find_include(payload: dict) -> list[str]:
    include = (
        payload.get("tool", {})
        .get("setuptools", {})
        .get("packages", {})
        .get("find", {})
        .get("include", [])
    )
    if not isinstance(include, list):
        return []
    return [str(item or "").strip() for item in include if str(item or "").strip()]


def _dependency_package_name(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for marker in (";", " ", "\t", "\r", "\n", "<", ">", "=", "~", "!", "["):
        if marker in text:
            text = text.split(marker, 1)[0]
    return text.strip()


def _normalized_package_metadata_payload(
    payload: dict[str, Any],
    *,
    extension_id: str,
    extension_version: str,
    manifest_dependencies: tuple[str, ...],
    backend_entry: str,
    extension_root: Path,
) -> tuple[dict[str, Any], list[str]]:
    normalized = _copy_toml_mapping(payload)
    updates: list[str] = []

    project = _ensure_mapping(normalized, "project")
    _set_if_changed(project, "name", extension_distribution_package(extension_id), updates, "project.name")
    _set_if_changed(project, "version", str(extension_version or "").strip(), updates, "project.version")

    dependencies = _normalize_project_dependencies(
        project.get("dependencies"),
        extension_id=extension_id,
        manifest_dependencies=manifest_dependencies,
    )
    _set_if_changed(project, "dependencies", dependencies, updates, "project.dependencies")

    entry_points = _ensure_mapping(project, "entry-points")
    extension_entry_points = _ensure_mapping(entry_points, "bias.extensions")
    expected_entry_key = extension_id.replace("-", "_")
    expected_backend_entry = str(backend_entry or "").strip()
    if expected_backend_entry and ":" not in expected_backend_entry:
        expected_backend_entry = f"{expected_backend_entry}:extend"
    _set_if_changed(
        extension_entry_points,
        expected_entry_key,
        expected_backend_entry,
        updates,
        f"project.entry-points.bias.extensions.{expected_entry_key}",
    )

    tool = _ensure_mapping(normalized, "tool")
    setuptools = _ensure_mapping(tool, "setuptools")
    _set_if_changed(setuptools, "include-package-data", True, updates, "tool.setuptools.include-package-data")
    packages = _ensure_mapping(setuptools, "packages")
    package_find = _ensure_mapping(packages, "find")
    _set_if_changed(package_find, "where", ["."], updates, "tool.setuptools.packages.find.where")
    _set_if_changed(
        package_find,
        "include",
        [f"{extension_python_package(extension_id)}*"],
        updates,
        "tool.setuptools.packages.find.include",
    )

    current_data_files = _project_data_files(normalized)
    synced_data_files = _normalize_data_files(
        current_data_files,
        extension_id=extension_id,
        extension_root=extension_root,
    )
    _set_if_changed(setuptools, "data-files", synced_data_files, updates, "tool.setuptools.data-files")

    return normalized, updates


def _normalize_project_dependencies(
    raw_dependencies: Any,
    *,
    extension_id: str,
    manifest_dependencies: tuple[str, ...],
) -> list[str]:
    existing = raw_dependencies if isinstance(raw_dependencies, list) else []
    preserved: list[str] = []
    seen_preserved: set[str] = set()

    for item in existing:
        text = str(item or "").strip()
        if not text:
            continue
        package_name = _dependency_package_name(text)
        if package_name == extension_distribution_package(extension_id):
            continue
        if package_name == "bias-core" or package_name.startswith("bias-ext-"):
            continue
        if text not in seen_preserved:
            preserved.append(text)
            seen_preserved.add(text)

    managed = ["bias-core>=0.1,<0.2"]

    return managed + preserved


def _normalize_data_files(
    data_files: dict,
    *,
    extension_id: str,
    extension_root: Path,
) -> dict[str, list[str]]:
    managed_prefix = f"bias_extensions/{extension_id}"
    normalized: dict[str, list[str]] = {}
    for key, value in data_files.items():
        target = str(key or "").strip().replace("\\", "/")
        if not target or target == managed_prefix or target.startswith(f"{managed_prefix}/"):
            continue
        if isinstance(value, list):
            files = [str(item or "").strip().replace("\\", "/") for item in value if str(item or "").strip()]
            if files:
                normalized[target] = sorted(dict.fromkeys(files))

    normalized[managed_prefix] = ["extension.json"]
    for file_name in _iter_package_source_files(extension_root):
        parent = str(Path(file_name).parent).replace("\\", "/")
        target = f"{managed_prefix}/{parent}"
        normalized.setdefault(target, []).append(file_name)

    return {
        target: sorted(dict.fromkeys(files))
        for target, files in sorted(normalized.items())
    }


def _copy_toml_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): _copy_toml_value(item)
        for key, item in value.items()
    }


def _copy_toml_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _copy_toml_mapping(value)
    if isinstance(value, list):
        return [_copy_toml_value(item) for item in value]
    return value


def _ensure_mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    current = payload.get(key)
    if not isinstance(current, dict):
        current = {}
        payload[key] = current
    return current


def _set_if_changed(
    payload: dict[str, Any],
    key: str,
    value: Any,
    updates: list[str],
    update_name: str,
) -> None:
    if payload.get(key) != value:
        payload[key] = value
        updates.append(update_name)


def _dump_pyproject_toml(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    project = payload.get("project", {}) if isinstance(payload.get("project"), dict) else {}
    _write_table(lines, "project", _without_nested_tables(project))

    project_entry_points = project.get("entry-points", {}) if isinstance(project.get("entry-points"), dict) else {}
    extension_entry_points = (
        project_entry_points.get("bias.extensions", {})
        if isinstance(project_entry_points.get("bias.extensions"), dict)
        else {}
    )
    if extension_entry_points:
        _write_table(lines, 'project.entry-points."bias.extensions"', extension_entry_points)

    optional_dependencies = (
        project.get("optional-dependencies", {})
        if isinstance(project.get("optional-dependencies"), dict)
        else {}
    )
    if optional_dependencies:
        _write_table(lines, "project.optional-dependencies", optional_dependencies)

    tool = payload.get("tool", {}) if isinstance(payload.get("tool"), dict) else {}
    setuptools = tool.get("setuptools", {}) if isinstance(tool.get("setuptools"), dict) else {}
    if setuptools:
        _write_table(lines, "tool.setuptools", _without_nested_tables(setuptools))

    package_find = (
        setuptools.get("packages", {}).get("find", {})
        if isinstance(setuptools.get("packages"), dict)
        else {}
    )
    if isinstance(package_find, dict) and package_find:
        _write_table(lines, "tool.setuptools.packages.find", package_find)

    data_files = setuptools.get("data-files", {}) if isinstance(setuptools.get("data-files"), dict) else {}
    if data_files:
        _write_table(lines, "tool.setuptools.data-files", data_files)

    project_excluded = {"entry-points", "optional-dependencies"}
    for key, value in project.items():
        if key in project_excluded or not isinstance(value, dict):
            continue
        _write_nested_table(lines, f"project.{key}", value)

    tool_excluded = {"setuptools"}
    for key, value in tool.items():
        if key in tool_excluded or not isinstance(value, dict):
            continue
        _write_nested_table(lines, f"tool.{key}", value)

    written_top_level = {"project", "tool"}
    for key, value in payload.items():
        if key in written_top_level:
            continue
        if isinstance(value, dict):
            _write_nested_table(lines, key, value)
        else:
            lines.append(f"{_format_toml_key(key)} = {_format_toml_value(value)}")

    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def _without_nested_tables(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if not isinstance(value, dict)
    }


def _write_table(lines: list[str], name: str, payload: dict[str, Any]) -> None:
    if lines:
        lines.append("")
    lines.append(f"[{name}]")
    for key, value in payload.items():
        lines.extend(_format_toml_assignment(key, value))


def _write_nested_table(lines: list[str], name: str, payload: dict[str, Any]) -> None:
    scalar_values = _without_nested_tables(payload)
    if scalar_values:
        _write_table(lines, name, scalar_values)
    for key, value in payload.items():
        if isinstance(value, dict):
            _write_nested_table(lines, f"{name}.{_format_toml_key(key)}", value)


def _format_toml_assignment(key: str, value: Any) -> list[str]:
    formatted_key = _format_toml_key(key)
    if isinstance(value, list) and len(value) > 1:
        lines = [f"{formatted_key} = ["]
        for item in value:
            lines.append(f"  {_format_toml_value(item)},")
        lines.append("]")
        return lines
    return [f"{formatted_key} = {_format_toml_value(value)}"]


def _format_toml_key(key: str) -> str:
    text = str(key)
    if all(part.replace("-", "_").isalnum() for part in text.split("-")) and "." not in text and "/" not in text:
        return text
    return _format_toml_string(text)


def _format_toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_format_toml_value(item) for item in value) + "]"
    return _format_toml_string(str(value))


def _format_toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _write_text_lf(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
