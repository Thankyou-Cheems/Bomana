import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";

describe("Launcher surface", () => {
  it("is a CDN entrypoint whose only native dependency is the read-only Bridge", async () => {
    const [html, main, client, bridgeRelease, appRelease] = await Promise.all([
      readFile(new URL("../../launcher.html", import.meta.url), "utf8"),
      readFile(new URL("./main.ts", import.meta.url), "utf8"),
      readFile(new URL("./launcher-client.ts", import.meta.url), "utf8"),
      readFile(new URL("./bridge-release.ts", import.meta.url), "utf8"),
      readFile(new URL("./app-web-release.ts", import.meta.url), "utf8"),
    ]);
    expect(html).toContain('src="/src/generated/bomana-logo.svg"');
    expect(html).toContain('id="launcher-host-state"');
    expect(html).toContain('id="account-panel"');
    expect(html).toContain('id="channel-grid"');
    expect(main).toContain('VITE_BRIDGE_URL || ""');
    expect(main).toContain("openBridgeAssetStore");
    expect(main).not.toMatch(/showDirectoryPicker|showOpenFilePicker|webkitdirectory|type="file"/);
    expect(main).not.toMatch(/\/commands|package_url|entrypoint|managed-root|child_process|channel\.install|channel\.rollback/);
    expect(html).not.toContain('id="persist-browser-cache"');
    expect(html).toContain('id="cache-map-list"');
    expect(html).toContain('class="readiness-card activity-panel hidden" id="cache-panel"');
    expect(html).toContain('id="connect-bridge"');
    expect(html).toContain('id="open-bridge"');
    expect(html).toContain('id="bridge-version-panel"');
    expect(html).toContain('id="update-bridge"');
    expect(html).toContain('id="download-bridge-diagnostics"');
    expect(html).toContain('../downloads/BomanaBridgeDiagnostics.exe');
    expect(html).toContain("运行连接诊断");
    expect(html).toContain('id="bridge-permission-guide"');
    expect(html).toContain("设备上的应用");
    expect(html).toContain("本地网络访问");
    expect(html).toContain("support.microsoft.com/zh-cn/edge/control-a-website-s-access-to-the-local-network-in-microsoft-edge");
    expect(main).toContain('probe.state === "permission-denied"');
    expect(main).toContain("权限已开放，重新连接");
    expect(html).not.toContain('id="anonymous-dau-enabled"');
    expect(html).toContain("默认匿名统计 · 每天最多一次 · 不含账号、游戏数据或 8111 内容");
    expect(main).not.toContain("setDailyActiveEnabled");
    expect(html).toContain('id="authorization-fallback-dialog"');
    expect(html).toContain('id="authorization-current-tab"');
    expect(main).not.toContain("scheduleBridgeProbe");
    expect(main).not.toContain("setInterval(() => void refreshBridge");
    expect(main).toContain("运行 Bridge 后点击连接");
    expect(main).toContain("bridgeVersionState");
    expect(main).toContain('updateBridge.classList.toggle("hidden", state !== "outdated")');
    expect(main).toContain("openAuthorizationPopup");
    expect(main).toContain('cachePanel.classList.toggle("hidden", !state.access.enhanced)');
    expect(main).toContain("showAuthorizationFallback");
    expect(main).toContain('searchParams.get("authorization") !== "complete"');
    expect(main).toContain('searchParams.get("intent") !== "Enhanced"');
    expect(main).toContain('accountPanel.classList.add("intent-highlight")');
    expect(main).toContain('window.addEventListener("message"');
    expect(main).toContain('return "轻量版"');
    expect(main).toContain('return "标准版"');
    expect(main).toContain('return "超级爆弹版"');
    expect(main).not.toContain('return "Lite 轻量版"');
    expect(main).not.toContain('return "Standard 标准版"');
    expect(main).not.toContain('return "Enhanced 超级爆弹版"');
    expect(main).toContain("包含 Lite 的计时功能");
    expect(main).toContain("包含 Standard 的全部功能");
    expect(main).toContain("复活周期计时与自定义时长");
    expect(main).toContain("纯计时界面，无导航与战术功能");
    expect(main).toContain("官方战区与机场目标切换");
    expect(main).toContain("不含格子坐标、聊天识别、战区倒计时与高程");
    expect(main).toContain("机场模块标记、Y66 标定与本机离线高程");
    expect(html).toContain("cheems-burger.webp");
    expect(client).toContain("storage: BrowserStorage = localStorage");
    expect(client).not.toContain("sessionStorage");
    expect(bridgeRelease).not.toContain("appWebVersion");
    expect(appRelease).toContain('mode: "same-origin"');
    expect(appRelease).toContain('redirect: "error"');
    expect(main).toContain("fetchAppWebRelease");
    expect(main).not.toContain("capabilities.app_web_version");
    expect(html).toContain("选择版本，立即进入 Bomana");
    expect(html).not.toContain("页面与计算逻辑自动保持最新");
    expect(html).toContain("超级爆弹订阅");
    expect(html).toContain("全真飞行");
    expect(html).toContain("需要的信息");
    expect(html).toContain("安静地放在手边");
    expect(main).toContain("`进入${displayChannel(channel)}`");
    expect(html).not.toMatch(/协议 v|Sigstore|SHA-256|OPFS|CDN AUTO/);
    expect(html).not.toMatch(/CDN Browser Launcher|Browser Runtime|Web Cockpit/);
  });

  it("is desktop and portrait-mobile responsive", async () => {
    const styles = await readFile(new URL("./styles.css", import.meta.url), "utf8");
    expect(styles).toContain("grid-template-columns: minmax(0, 1.7fr) minmax(285px, .72fr)");
    expect(styles).toContain("@media (max-width: 760px)");
    expect(styles).toContain("grid-template-columns: 1fr");
    expect(styles).toContain("grid-template-rows: auto minmax(68px, auto) 1fr auto");
    expect(styles).toContain("white-space: nowrap");
    expect(styles).toContain("min-height: 52px");
  });

  it("switches the missing-Bridge action after a download is triggered", async () => {
    const [html, main] = await Promise.all([
      readFile(new URL("../../launcher.html", import.meta.url), "utf8"),
      readFile(new URL("./main.ts", import.meta.url), "utf8"),
    ]);
    expect(html).toContain('id="download-bridge"');
    expect(main).toContain("markBridgeDownloadStarted");
    expect(main).toContain('actionButton("连接 Bridge"');
    expect(main).toContain("请手动运行下载好的 BomanaBridge.exe，看到系统托盘图标则代表启动成功");
  });
});
