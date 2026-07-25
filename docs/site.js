const repository = "Thankyou-Cheems/Bomana";
const githubReleasesUrl = `https://github.com/${repository}/releases`;
const githubReleasesApi = `https://api.github.com/repos/${repository}/releases?per_page=20`;

/** EdgeOne-accelerated update CDN (Tencent). Primary for China and site mirror. */
const cdnBase = "https://bomanaupdate.ruikang.wang";
const cdnLauncherApi = `${cdnBase}/api/v1/launcher`;
const cdnVersionApi = (channel) =>
  `${cdnBase}/api/v1/version?channel=${encodeURIComponent(channel)}`;

/** Same-origin static catalog — no GitHub required for the page to work. */
const catalogUrl = "download-catalog.json";

const statusEl = document.querySelector("#releaseStatus");
const releaseAssets = document.querySelector("#releaseAssets");
const launcherDownload = document.querySelector("#launcherDownload");
const heroDownload = document.querySelector("#heroDownload");
const ctaDownload = document.querySelector("#ctaDownload");
const launcherDownloadGithub = document.querySelector("#launcherDownloadGithub");
const heroDownloadGithub = document.querySelector("#heroDownloadGithub");
const ctaDownloadGithub = document.querySelector("#ctaDownloadGithub");
const allReleasesLink = document.querySelector("#allReleasesLink");

const CHANNELS = ["Enhanced", "Standard", "Lite"];
const CHANNEL_LABELS = {
  Enhanced: "超级爆弹版",
  Standard: "Standard",
  Lite: "Lite",
};

function isLauncher(name) {
  return /launcher.*[.]exe$/i.test(String(name || ""));
}

function setGithubFallback(href) {
  const url = href || githubReleasesUrl;
  for (const el of [launcherDownloadGithub, heroDownloadGithub, ctaDownloadGithub, allReleasesLink]) {
    if (el) el.href = url;
  }
}

function setPrimaryDownload(url, label) {
  if (!url) return;
  for (const el of [launcherDownload, heroDownload, ctaDownload]) {
    if (!el) continue;
    el.href = url;
  }
  if (label && launcherDownload) {
    launcherDownload.textContent = label;
  }
  if (heroDownload) {
    heroDownload.textContent = "下载 Windows 启动器";
  }
  if (ctaDownload) {
    ctaDownload.textContent = "下载启动器（国内 CDN）";
  }
}

function appendAssetLink(container, href, label, title) {
  const link = document.createElement("a");
  link.href = href;
  link.textContent = label;
  if (title) link.title = title;
  link.rel = "noopener";
  container.append(link);
}

function renderCdnAssets(catalog) {
  if (!releaseAssets) return;
  releaseAssets.replaceChildren();

  const launcher = catalog.launcher || {};
  if (launcher.package_url) {
    const name = launcher.asset || launcher.package_url.split("/").pop() || "launcher";
    appendAssetLink(
      releaseAssets,
      launcher.package_url,
      `Launcher ${launcher.version || ""}`.trim(),
      name,
    );
  }

  const channels = catalog.channels || {};
  for (const channel of CHANNELS) {
    const entry = channels[channel];
    if (!entry?.package_url) continue;
    appendAssetLink(
      releaseAssets,
      entry.package_url,
      `${CHANNEL_LABELS[channel] || channel} v${entry.app_version || ""}`.trim(),
      entry.asset || entry.package_url,
    );
  }

  if (!releaseAssets.childElementCount) {
    const span = document.createElement("span");
    span.textContent = "CDN 文件列表暂不可用";
    releaseAssets.append(span);
  }
}

async function fetchJson(url, init) {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error(`${url} → ${response.status}`);
  return response.json();
}

async function loadStaticCatalog() {
  return fetchJson(catalogUrl, { cache: "no-cache" });
}

async function loadCdnCatalog() {
  const launcher = await fetchJson(cdnLauncherApi, { cache: "no-cache" });
  const channels = {};
  await Promise.all(
    CHANNELS.map(async (channel) => {
      try {
        channels[channel] = await fetchJson(cdnVersionApi(channel), { cache: "no-cache" });
      } catch (error) {
        console.warn(`CDN channel ${channel} unavailable`, error);
      }
    }),
  );
  return {
    schema_version: 1,
    primary_source: "TencentCloud",
    cdn_base: cdnBase,
    launcher: {
      version: launcher.launcher_version || launcher.version || "",
      package_url: launcher.package_url || "",
      asset: launcher.launcher_asset || launcher.package_asset || "",
      sha256: launcher.launcher_sha256 || launcher.package_sha256 || "",
    },
    channels: Object.fromEntries(
      Object.entries(channels).map(([channel, body]) => [
        channel,
        {
          app_version: body.app_version || "",
          package_url: body.package_url || "",
          asset: body.package_asset || "",
          sha256: body.package_sha256 || "",
        },
      ]),
    ),
    github_releases_url: githubReleasesUrl,
  };
}

function applyCatalog(catalog, sourceLabel) {
  const launcherUrl = catalog?.launcher?.package_url || "";
  const version = catalog?.launcher?.version || "";
  if (launcherUrl) {
    const label = version
      ? `下载启动器 v${version}（国内 CDN）`
      : "下载启动器（国内 CDN）";
    setPrimaryDownload(launcherUrl, label);
  }
  setGithubFallback(catalog?.github_releases_url || githubReleasesUrl);
  renderCdnAssets(catalog || {});

  if (statusEl) {
    const parts = [];
    if (version) parts.push(`启动器 v${version}`);
    const enhanced = catalog?.channels?.Enhanced?.app_version;
    if (enhanced) parts.push(`超级爆弹版 v${enhanced}`);
    const summary = parts.length ? parts.join(" · ") : "版本信息已就绪";
    statusEl.textContent = `${summary}。主下载：腾讯云 EdgeOne CDN（${sourceLabel}）；GitHub 为备用。`;
  }
}

async function loadGithubBackupLinksOnly() {
  // Optional enrichment for the GitHub backup link target; never used as primary.
  try {
    const response = await fetch(githubReleasesApi, {
      headers: { Accept: "application/vnd.github+json" },
    });
    if (!response.ok) return;
    const releases = await response.json();
    const withLauncher = releases.find((release) =>
      (release.assets || []).some((asset) => isLauncher(asset.name)),
    );
    const release = withLauncher || releases[0];
    if (release?.html_url) {
      setGithubFallback(release.html_url);
    }
  } catch (error) {
    console.warn("GitHub backup metadata unavailable (expected in some regions)", error);
  }
}

async function loadRelease() {
  setGithubFallback(githubReleasesUrl);

  let catalog = null;
  let sourceLabel = "catalog";

  // 1) Prefer live CDN API (EdgeOne). Works from China and from the Tencent mirror.
  try {
    catalog = await loadCdnCatalog();
    sourceLabel = "live API";
  } catch (error) {
    console.warn("CDN API unavailable, falling back to static catalog", error);
  }

  // 2) Same-origin static catalog (baked at deploy time; no GitHub on server).
  if (!catalog?.launcher?.package_url) {
    try {
      catalog = await loadStaticCatalog();
      sourceLabel = "static catalog";
    } catch (error) {
      console.warn("Static download catalog unavailable", error);
    }
  }

  if (catalog?.launcher?.package_url) {
    applyCatalog(catalog, sourceLabel);
  } else if (statusEl) {
    statusEl.textContent =
      "暂时无法读取国内 CDN 版本信息。请使用 GitHub 备用下载，或稍后重试。";
    setPrimaryDownload(githubReleasesUrl, "打开 GitHub Releases（临时）");
  }

  // 3) Best-effort GitHub metadata for backup deep-link only (may fail in CN).
  loadGithubBackupLinksOnly();
}

function loadShotPlaceholders() {
  const shots = document.querySelectorAll(".shot[data-shot]");
  for (const shot of shots) {
    const path = shot.getAttribute("data-shot");
    const img = shot.querySelector(".shot-img");
    if (!path || !img) continue;

    const probe = new Image();
    probe.onload = () => {
      // CSS uses width:100%; height:auto so product screenshots are never cropped.
      img.src = path;
      if (probe.naturalWidth > 0 && probe.naturalHeight > 0) {
        img.width = probe.naturalWidth;
        img.height = probe.naturalHeight;
      }
      img.hidden = false;
      shot.classList.add("is-loaded");
    };
    probe.onerror = () => {
      // Keep designed empty slot until a real screenshot is uploaded.
    };
    probe.src = path;
  }
}

loadRelease();
loadShotPlaceholders();
