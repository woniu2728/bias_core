def get_version_file_path(base_dir):
    from pathlib import Path
    return Path(base_dir) / "VERSION"
