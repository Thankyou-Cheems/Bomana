from bomana import metadata
from bomana.config import Theme, __version__
from bomana.ui.theme import Theme as RuntimeTheme


def test_config_reexports_project_metadata() -> None:
    assert __version__ == metadata.__version__


def test_config_reexports_runtime_theme() -> None:
    assert Theme is RuntimeTheme
