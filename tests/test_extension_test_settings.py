from pathlib import Path
from unittest.mock import patch


def test_extension_test_settings_resolves_workspace_from_extension_cwd(tmp_path):
    from bias_core import extension_test_settings

    workspace = tmp_path / "workspace"
    extension = workspace / "bias-ext-alpha"
    extension.mkdir(parents=True)
    (extension / "extension.json").write_text("{}", encoding="utf-8")

    with patch("pathlib.Path.cwd", return_value=extension):
        assert extension_test_settings._resolve_workspace_root() == workspace.resolve()


def test_extension_test_settings_uses_configured_workspace_root(tmp_path, monkeypatch):
    from bias_core import extension_test_settings

    configured = tmp_path / "configured-workspace"
    monkeypatch.setenv("BIAS_EXTENSION_WORKSPACE_ROOT", str(configured))

    assert extension_test_settings._resolve_workspace_root() == configured.resolve()
