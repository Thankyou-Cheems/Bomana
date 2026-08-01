from __future__ import annotations


def test_public_runtime_imports_without_subscriber_modules() -> None:
    import bomana.config.settings
    import bomana.core.lifecycle
    import bomana.core.logic
    import bomana.core.release_state
    import bomana.ui.app
    import bomana.ui.dialogs
    import bomana.ui.main_window
    import bomana.ui.nav_window
    import bomana.ui.panel_presenter
    import bomana.ui.runtime_services  # noqa: F401
