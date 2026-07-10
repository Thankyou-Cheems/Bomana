const repository = "Thankyou-Cheems/Bomana";
const releasesApi = `https://api.github.com/repos/${repository}/releases?per_page=20`;
const releasesUrl = `https://github.com/${repository}/releases`;

const statusEl = document.querySelector("#releaseStatus");
const releaseAssets = document.querySelector("#releaseAssets");
const launcherDownload = document.querySelector("#launcherDownload");
const heroDownload = document.querySelector("#heroDownload");
const setupDownload = document.querySelector("#setupDownload");
const allReleasesLink = document.querySelector("#allReleasesLink");

function isLauncher(name) {
  return /launcher.*[.]exe$/i.test(name);
}

function isBrokerSetup(name) {
  return /^BomanaHotkeyBrokerSetup[.]exe$/i.test(name);
}

function releaseHasLauncher(release) {
  return release.assets.some((asset) => isLauncher(asset.name));
}

function chooseRelease(releases) {
  return releases.find(releaseHasLauncher) || releases[0];
}

function friendlyAssetLabel(name) {
  if (isLauncher(name)) return "Windows Launcher";
  if (isBrokerSetup(name)) return "Signed Hotkey Broker";
  if (/checksums/i.test(name)) return "Checksums";
  if (/manifest/i.test(name)) return "Signed manifest";
  if (/app_Enhanced/i.test(name)) return "Enhanced app";
  if (/app_Standard/i.test(name)) return "Standard app";
  if (/app_Lite/i.test(name)) return "Lite app";
  return name;
}

function assetRank(name) {
  if (isLauncher(name)) return 0;
  if (isBrokerSetup(name)) return 1;
  if (/checksums/i.test(name)) return 2;
  if (/manifest/i.test(name)) return 3;
  if (/app_Enhanced/i.test(name)) return 4;
  if (/app_Standard/i.test(name)) return 5;
  if (/app_Lite/i.test(name)) return 6;
  return 7;
}

function renderAssets(release) {
  const selected = [...release.assets]
    .sort((left, right) => assetRank(left.name) - assetRank(right.name))
    .slice(0, 8);
  releaseAssets.replaceChildren();

  for (const asset of selected) {
    const link = document.createElement("a");
    link.href = asset.browser_download_url;
    link.textContent = friendlyAssetLabel(asset.name);
    link.title = asset.name;
    releaseAssets.append(link);
  }
}

async function loadRelease() {
  try {
    const response = await fetch(releasesApi, {
      headers: { Accept: "application/vnd.github+json" },
    });
    if (!response.ok) throw new Error(`GitHub API returned ${response.status}`);

    const releases = await response.json();
    const release = chooseRelease(releases);
    if (!release) throw new Error("No releases found");

    const launcher = release.assets.find((asset) => isLauncher(asset.name));
    const brokerSetup = release.assets.find((asset) => isBrokerSetup(asset.name));
    const label = release.name || release.tag_name;
    statusEl.textContent = `当前推荐：${label}。启动器会自动选择并验证应用通道。`;
    allReleasesLink.href = releasesUrl;

    if (launcher) {
      launcherDownload.href = launcher.browser_download_url;
      heroDownload.href = launcher.browser_download_url;
      launcherDownload.textContent = `下载 ${launcher.name}`;
      heroDownload.textContent = "下载 Windows 启动器";
    } else {
      launcherDownload.href = release.html_url || releasesUrl;
      heroDownload.href = release.html_url || releasesUrl;
    }

    if (brokerSetup) {
      setupDownload.href = brokerSetup.browser_download_url;
      setupDownload.textContent = "下载签名热键组件";
    } else {
      setupDownload.href = release.html_url || releasesUrl;
      setupDownload.textContent = "查看热键组件说明";
    }

    renderAssets(release);
  } catch (error) {
    console.warn("Unable to load Bomana releases", error);
    statusEl.textContent = "暂时无法读取版本信息，请直接打开 GitHub Releases。";
    launcherDownload.href = releasesUrl;
    heroDownload.href = releasesUrl;
    setupDownload.href = releasesUrl;
  }
}

loadRelease();
