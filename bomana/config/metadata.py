"""Compatibility metadata exports for `bomana.config`."""

from bomana import metadata as _metadata
from bomana.ui import theme as _theme

__title__ = _metadata.__title__
__version__ = _metadata.__version__
PORTABLE_MIN_LAUNCHER_VERSION = _metadata.PORTABLE_MIN_LAUNCHER_VERSION
__author__ = _metadata.__author__
__license__ = _metadata.__license__
__copyright__ = _metadata.__copyright__
__repository__ = _metadata.__repository__
Theme = _theme.Theme

__all__ = [
    "PORTABLE_MIN_LAUNCHER_VERSION",
    "Theme",
    "__author__",
    "__copyright__",
    "__license__",
    "__repository__",
    "__title__",
    "__version__",
]
