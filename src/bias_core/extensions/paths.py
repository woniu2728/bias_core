from __future__ import annotations

from pathlib import Path


FOUNDATION_EXTENSION_PACKAGES: dict[str, tuple[str, str]] = {
    "content": ("bias-content", "bias_content"),
}


def is_foundation_extension(extension_id: str) -> bool:
    return str(extension_id or "").strip().replace("-", "_") in FOUNDATION_EXTENSION_PACKAGES


def extension_distribution_package(extension_id: str) -> str:
    normalized = str(extension_id or "").strip()
    if not normalized:
        return ""
    foundation = FOUNDATION_EXTENSION_PACKAGES.get(normalized.replace("-", "_"))
    if foundation:
        return foundation[0]
    return f"bias-ext-{normalized}"


def extension_python_package(extension_id: str) -> str:
    normalized = str(extension_id or "").strip().replace("-", "_")
    foundation = FOUNDATION_EXTENSION_PACKAGES.get(normalized)
    if foundation:
        return foundation[1]
    return f"bias_ext_{normalized}" if normalized else ""


def legacy_extension_python_package(extension_id: str) -> str:
    normalized = str(extension_id or "").strip().replace("-", "_")
    return f"extensions.{normalized}" if normalized else ""


def extension_workspace_dir_name(extension_id: str) -> str:
    normalized = str(extension_id or "").strip()
    return f"bias-ext-{normalized}" if normalized else ""


def module_path(entry: str) -> str:
    return str(entry or "").strip().split(":", 1)[0]


def module_file_from_entry(root_path: Path, entry: str, extension_id: str) -> Path | None:
    normalized_entry = module_path(entry)
    if not normalized_entry:
        return None

    package = extension_python_package(extension_id)
    legacy_package = legacy_extension_python_package(extension_id)
    if package and normalized_entry.startswith(f"{package}."):
        return root_path.joinpath(*normalized_entry.split(".")).with_suffix(".py")
    if legacy_package and normalized_entry.startswith(f"{legacy_package}."):
        relative_module = normalized_entry[len(legacy_package) + 1:]
        return root_path.joinpath(*relative_module.split(".")).with_suffix(".py")
    return None


def extension_backend_dir(root_path: Path, extension_id: str) -> Path:
    package = extension_python_package(extension_id)
    packaged_backend = root_path / package / "backend" if package else root_path / "backend"
    if packaged_backend.exists() or not (root_path / "backend").exists():
        return packaged_backend
    return root_path / "backend"


def extension_django_migration_dir(root_path: Path, extension_id: str) -> Path:
    return extension_backend_dir(root_path, extension_id) / "django_migrations"


def resolve_manifest_migration_module(manifest, extension_id: str) -> str:
    declared = str(getattr(manifest, "django_migration_module", "") or "").strip()
    if declared:
        return declared
    app_config = str(getattr(manifest, "django_app_config", "") or "").strip()
    if not app_config:
        return ""
    module_prefix = app_config.rsplit(".apps.", 1)[0]
    if module_prefix and module_prefix != app_config:
        return f"{module_prefix}.django_migrations"
    package = extension_python_package(extension_id)
    return f"{package}.backend.django_migrations" if package else ""


def frontend_entry_path(root_path: Path | None, entry: str, extension_id: str) -> Path | None:
    if root_path is None:
        return None
    normalized = str(entry or "").strip().replace("\\", "/").lstrip("/")
    if not normalized:
        return None

    path = Path(normalized)
    if path.is_absolute():
        return path

    if normalized.startswith("extensions/"):
        parts = normalized.split("/", 2)
        if len(parts) == 3:
            declared_id = parts[1]
            relative = parts[2]
            if root_path.name in {declared_id, extension_workspace_dir_name(declared_id)}:
                return root_path / relative
            sibling = root_path.parent / extension_workspace_dir_name(declared_id) / relative
            if sibling.exists():
                return sibling
            return root_path.parent / declared_id / relative
        return root_path / normalized

    if normalized.startswith(f"{extension_workspace_dir_name(extension_id)}/"):
        relative = normalized.split("/", 1)[1]
        return root_path / relative

    return root_path / normalized


def frontend_entry_key(root_path: Path | None, entry: str, extension_id: str) -> str:
    normalized = str(entry or "").strip().replace("\\", "/").lstrip("/")
    if not normalized:
        return ""
    if normalized.startswith("extensions/"):
        return normalized
    if root_path is not None and root_path.name == extension_workspace_dir_name(extension_id):
        return f"{root_path.name}/{normalized}"
    return normalized
