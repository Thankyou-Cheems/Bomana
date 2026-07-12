from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

ALLOWED_EXTERNAL_NETLOCS = {
    "docs.github.com",
    "github.com",
    "thankyou-cheems.github.io",
    "bomanaupdate.ruikang.wang",
    "ruikang.wang",
}


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
        "launcherDownloadGithub",
        "releaseStatus",
        "releaseAssets",
    } <= parser.ids
    assert "提权只给热键，不给整个应用" in html
    assert "三步开始" in html
    assert "只读官方 localhost:8111" in html
    assert "Artifact Attestations" in html
    assert "国内 CDN" in html
    assert "GitHub 备用" in html
    assert parser.inline_scripts == 0


def test_github_pages_local_assets_exist_and_no_external_runtime_assets() -> None:
    parser = SiteParser()
    parser.feed((DOCS / "index.html").read_text(encoding="utf-8"))

    missing = sorted(asset for asset in parser.local_assets if not (DOCS / asset).is_file())
    assert missing == []
    assert not [
        asset
        for asset in parser.external_assets
        if urlparse(asset).netloc not in ALLOWED_EXTERNAL_NETLOCS
    ]


def test_download_catalog_points_at_tencent_cdn() -> None:
    import json

    catalog = json.loads((DOCS / "download-catalog.json").read_text(encoding="utf-8"))
    assert catalog["primary_source"] == "TencentCloud"
    assert catalog["cdn_base"].startswith("https://bomanaupdate.ruikang.wang")
    assert catalog["launcher"]["package_url"].startswith(
        "https://bomanaupdate.ruikang.wang/downloads/"
    )
    assert "Enhanced" in catalog["channels"]
    assert catalog["channels"]["Enhanced"]["package_url"].startswith(
        "https://bomanaupdate.ruikang.wang/downloads/"
    )


def test_site_styles_are_responsive_and_accessible() -> None:
    css = (DOCS / "styles.css").read_text(encoding="utf-8")
    javascript = (DOCS / "site.js").read_text(encoding="utf-8")

    assert "@media (max-width: 640px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert ":focus-visible" in css
    assert ".skip-link" in css
    assert "gallery-stack" in css
    assert "height: auto" in css
    assert "bomanaupdate.ruikang.wang" in javascript
    assert "download-catalog.json" in javascript
    assert "api.github.com" in javascript  # backup metadata only
    assert "BomanaHotkeyBrokerSetup" not in javascript
    assert "textContent" in javascript
    assert "innerHTML" not in javascript


def test_deploy_pages_mirror_tool_is_local_push_only() -> None:
    source = (ROOT / "tools" / "deploy_pages_mirror.py").read_text(encoding="utf-8")
    assert "never pull from GitHub" in source or "never fetches GitHub" in source
    assert "TencentCloudPublic" in source
    assert "/opt/Website/bomana" in source
    assert "scp" in source
    # Must not instruct the remote to clone or curl GitHub.
    assert "git clone" not in source
    assert "api.github.com" not in source
