import bomana.config as config
import bomana.config.settings as settings
from bomana import metadata
from bomana.metadata import __version__
from bomana.ui.theme import Theme
from bomana.ui.theme import Theme as RuntimeTheme


def test_project_metadata_imports_from_metadata_module() -> None:
    assert __version__ == metadata.__version__


def test_runtime_theme_imports_from_ui_theme_module() -> None:
    assert Theme is RuntimeTheme


def test_config_package_exposes_only_submodule_boundary() -> None:
    assert config.__all__ == ["feature_profile", "settings", "static_data"]
    assert settings.PanelConfig
    assert not hasattr(config, "PanelConfig")
    assert not hasattr(config, "Theme")
    assert not hasattr(config, "__version__")
