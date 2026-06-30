const repository = "Thankyou-Cheems/Bomana";
const releasesApi = `https://api.github.com/repos/${repository}/releases?per_page=20`;
const releasesUrl = `https://github.com/${repository}/releases`;

const statusEl = document.querySelector("#releaseStatus");
const assetGrid = document.querySelector("#assetGrid");
const launcherDownload = document.querySelector("#launcherDownload");
const heroDownload = document.querySelector("#heroDownload");
const allReleasesLink = document.querySelector("#allReleasesLink");

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "size unknown";
  }

  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unitIndex = 0;

  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }

  return `${value.toFixed(value >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

function classifyAsset(name) {
  if (/launcher.*[.]exe$/i.test(name)) {
    return "Launcher";
  }
  if (/checksums/i.test(name)) {
    return "Checksum";
  }
  if (/manifest/i.test(name)) {
    return "Signed manifest";
  }
  if (/app_Enhanced.*[.]zip$/i.test(name)) {
    return "Enhanced app";
  }
  if (/app_Standard.*[.]zip$/i.test(name)) {
    return "Standard app";
  }
  if (/app_Lite.*[.]zip$/i.test(name)) {
    return "Lite app";
  }
  return "Release file";
}

function assetRank(asset) {
  const name = asset.name;
  if (/launcher.*[.]exe$/i.test(name)) return 0;
  if (/app_Enhanced.*[.]zip$/i.test(name)) return 1;
  if (/app_Standard.*[.]zip$/i.test(name)) return 2;
  if (/app_Lite.*[.]zip$/i.test(name)) return 3;
  if (/checksums/i.test(name)) return 4;
  if (/manifest/i.test(name)) return 5;
  return 6;
}

function renderAssets(release) {
  const assets = [...release.assets].sort((a, b) => assetRank(a) - assetRank(b) || a.name.localeCompare(b.name));
  assetGrid.replaceChildren();

  for (const asset of assets) {
    const link = document.createElement("a");
    link.className = "asset-link";
    link.href = asset.browser_download_url;
    link.textContent = asset.name;

    const detail = document.createElement("span");
    detail.textContent = `${classifyAsset(asset.name)} - ${formatBytes(asset.size)}`;
    link.append(detail);
    assetGrid.append(link);
  }
}

function releaseHasLauncher(release) {
  return release.assets.some((asset) => /launcher.*[.]exe$/i.test(asset.name));
}

function chooseRelease(releases) {
  return releases.find(releaseHasLauncher) || releases[0];
}

async function loadReleases() {
  try {
    const response = await fetch(releasesApi, {
      headers: {
        Accept: "application/vnd.github+json",
      },
    });

    if (!response.ok) {
      throw new Error(`GitHub API returned ${response.status}`);
    }

    const releases = await response.json();
    const release = chooseRelease(releases);

    if (!release) {
      throw new Error("GitHub API returned no releases");
    }

    const launcher = release.assets.find((asset) => /launcher.*[.]exe$/i.test(asset.name));
    const releaseLabel = `${release.name || release.tag_name}`;

    statusEl.textContent = `当前推荐版本：${releaseLabel}`;
    allReleasesLink.href = releasesUrl;

    if (launcher) {
      launcherDownload.href = launcher.browser_download_url;
      heroDownload.href = launcher.browser_download_url;
      launcherDownload.textContent = `下载 ${launcher.name}`;
      heroDownload.textContent = "下载最新版启动器";
    } else {
      launcherDownload.href = release.html_url || releasesUrl;
      heroDownload.href = release.html_url || releasesUrl;
      launcherDownload.textContent = "打开推荐 Release";
    }

    renderAssets(release);
  } catch (error) {
    console.warn("Unable to load Bomana releases", error);
    statusEl.textContent = "无法自动读取版本列表，请使用 GitHub Releases 入口。";
    launcherDownload.href = releasesUrl;
    heroDownload.href = releasesUrl;
  }
}

loadReleases();
