from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


class SiteParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.local_assets: set[str] = set()
        self.inline_scripts = 0
        self.external_assets: set[str] = set()

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        if element_id := values.get("id"):
            self.ids.add(element_id)
        if tag == "script" and not values.get("src"):
            self.inline_scripts += 1
        for attribute in ("href", "src"):
            value = values.get(attribute, "")
            if not value or value.startswith(("#", "mailto:")):
                continue
            parsed = urlparse(value)
            if parsed.scheme in ("http", "https"):
                self.external_assets.add(value)
            elif not parsed.scheme:
                self.local_assets.add(parsed.path)


def test_github_pages_site_has_new_user_and_permission_paths() -> None:
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    parser = SiteParser()
    parser.feed(html)

    assert {
        "content",
        "start",
        "features",
        "hotkeys",
        "docs",
        "heroDownload",
        "launcherDownload",
        "setupDownload",
        "releaseStatus",
        "releaseAssets",
    } <= parser.ids
    assert "提权只给热键，不给整个应用" in html
    assert "三步开始" in html
    assert "只读官方 localhost:8111" in html
    assert parser.inline_scripts == 0


def test_github_pages_local_assets_exist_and_no_external_runtime_assets() -> None:
    parser = SiteParser()
    parser.feed((DOCS / "index.html").read_text(encoding="utf-8"))

    missing = sorted(asset for asset in parser.local_assets if not (DOCS / asset).is_file())
    assert missing == []
    assert not [
        asset
        for asset in parser.external_assets
        if urlparse(asset).netloc not in {"github.com", "thankyou-cheems.github.io"}
    ]


def test_site_styles_are_responsive_and_accessible() -> None:
    css = (DOCS / "styles.css").read_text(encoding="utf-8")
    javascript = (DOCS / "site.js").read_text(encoding="utf-8")

    assert "@media (max-width: 640px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert ":focus-visible" in css
    assert ".skip-link" in css
    assert "api.github.com" in javascript
    assert "BomanaHotkeyBrokerSetup" in javascript
    assert "textContent" in javascript
    assert "innerHTML" not in javascript
