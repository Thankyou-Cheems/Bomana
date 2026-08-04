from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

ALLOWED_EXTERNAL_NETLOCS = {
    "docs.github.com",
    "github.com",
    "forum.warthunder.com",
    "legal.gaijin.net",
    "pay.ruikang.wang",
    "thankyou-cheems.github.io",
    "bomanaupdate.ruikang.wang",
    "bomana.ruikang.wang",
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
        "greenDownload",
        "releaseStatus",
        "releaseAssets",
    } <= parser.ids
    assert "系统热键只控制 Bomana" in html
    assert "三步开始" in html
    assert "只读官方 localhost:8111" in html
    assert "Artifact Attestations" in html
    assert "国内 CDN" in html
    assert "GitHub 备用" in html
    assert "没有“绝对安全”或“绝不封号”保证" in html
    assert "只读取游戏提供的 localhost:8111 信息" in html
    assert "WTRTI" in html
    assert "第三方辅助" not in html
    assert "立即购买 / 试用" in html
    assert "https://pay.ruikang.wang/" in html
    assert '<link rel="canonical" href="https://bomana.ruikang.wang/">' in html
    assert 'property="og:url" content="https://bomana.ruikang.wang/"' in html
    assert "https://ruikang.wang/bomana/" not in html
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
    catalog = json.loads((DOCS / "download-catalog.json").read_text(encoding="utf-8"))
    assert catalog["primary_source"] == "TencentCloud"
    assert catalog["cdn_base"].startswith("https://bomanaupdate.ruikang.wang")
    assert catalog["launcher"]["package_url"].startswith(
        "https://bomanaupdate.ruikang.wang/downloads/"
    )
    assert set(catalog["channels"]) == {"Standard", "Lite"}
    assert all(
        entry["package_url"].startswith("https://bomanaupdate.ruikang.wang/downloads/")
        for entry in catalog["channels"].values()
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
    assert ".trust-grid article {\n  min-width: 0;" in css
    assert "scroll-margin-top: 100px;" in css
    assert "bomanaupdate.ruikang.wang" in javascript
    assert "download-catalog.json" in javascript
    assert "loadStaticCatalog()" in javascript
    assert "/api/v1/launcher" not in javascript
    assert "/api/v1/version" not in javascript
    assert "api.github.com" in javascript  # backup metadata only
    assert "Bomana_Green_Lite" in javascript
    assert "setGreenDownload(greenAsset)" in javascript
    assert "BomanaHotkeyBrokerSetup" not in javascript
    assert "textContent" in javascript
    assert "innerHTML" not in javascript


def test_glacier_gallery_metadata_matches_image_dimensions() -> None:
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    shot_names = (
        "desktop-main.png",
        "launcher.png",
        "nav-precision.png",
        "nav-hud.png",
    )

    for name in shot_names:
        marker = f'data-shot="assets/shots/{name}"'
        marker_index = html.index(marker)
        fragment = html[marker_index : marker_index + 700]
        with Image.open(DOCS / "assets" / "shots" / name) as image:
            width, height = image.size
        assert f'width="{width}"' in fragment
        assert f'height="{height}"' in fragment


def test_deploy_pages_mirror_tool_is_local_push_only() -> None:
    source = (ROOT / "tools" / "deploy_pages_mirror.py").read_text(encoding="utf-8")
    assert "never pull from GitHub" in source or "never fetches GitHub" in source
    assert "TencentCloudPublic" in source
    assert "/opt/Website/bomana" in source
    assert 'DEFAULT_PUBLIC_BASE_URL = "https://bomana.ruikang.wang"' in source
    assert 'DEFAULT_CDN_BASE = "https://bomanaupdate.ruikang.wang"' in source
    assert "scp" in source
    # Must not instruct the remote to clone or curl GitHub.
    assert "git clone" not in source
    assert "api.github.com" not in source


def test_public_site_cutover_keeps_launcher_update_origin_independent() -> None:
    launcher = (ROOT / "launcher.pyw").read_text(encoding="utf-8")
    distribution = (ROOT / "launcher" / "distribution_build.py").read_text(encoding="utf-8")
    guide = (DOCS / "guides" / "public-site-cutover.md").read_text(encoding="utf-8")

    assert '"https://bomanaupdate.ruikang.wang"' in distribution
    assert "distribution_build" in launcher
    assert "bomana.ruikang.wang" in guide
    assert "bomanaupdate.ruikang.wang" in guide
    assert "short-lived CheemsPay-derived grant" not in guide
    assert "private manifest/artifact endpoints is denied" in guide
    assert "byte-level checks" in guide


def test_public_site_edgeone_configuration_is_host_scoped() -> None:
    deploy = ROOT / "deploy" / "bomana-pages"
    domain = json.loads((deploy / "edgeone-domain.template.json").read_text(encoding="utf-8"))
    rule = json.loads((deploy / "edgeone-rule.template.json").read_text(encoding="utf-8"))
    caddy = (deploy / "Caddyfile.snippet").read_text(encoding="utf-8")
    redirect = (deploy / "legacy-redirect.caddy").read_text(encoding="utf-8")

    assert domain["DomainName"] == "bomana.ruikang.wang"
    assert domain["OriginProtocol"] == "HTTPS"
    assert domain["OriginInfo"]["HostHeader"] == "bomana.ruikang.wang"
    assert rule["Branches"][0]["Condition"] == ("${http.request.host} in ['bomana.ruikang.wang']")
    action_names = {action["Name"] for action in rule["Branches"][0]["Actions"]}
    assert {"OriginPullProtocol", "ForceRedirectHTTPS", "OfflineCache"} <= action_names
    assert "https://bomana.ruikang.wang{uri}" in redirect
    assert "https://bomana.ruikang.wang" in caddy

    scoped_config = caddy + redirect + json.dumps(domain) + json.dumps(rule)
    assert "bomanaupdate.ruikang.wang" not in scoped_config
