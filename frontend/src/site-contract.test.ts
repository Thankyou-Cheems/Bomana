import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";

describe("public site contract", () => {
  it("uses the Online Launcher as the hero, top-bar, and final CTA", async () => {
    const html = await readFile(new URL("../../docs/index.html", import.meta.url), "utf8");
    expect(html).toContain('class="nav-launcher" href="/launcher/"');
    expect(html.match(/href="\/launcher\/"/g)?.length).toBeGreaterThanOrEqual(3);
    expect(html).toContain("在线启动 Bomana");
    expect(html).toContain("Lite 只保留复活周期计时");
    expect(html).toContain("Standard 提供官方战区与机场的基础导航");
    for (const retired of ["Bomana_launcher_v", "Lite 绿色版", "下载启动器（国内 CDN）", "内置 Python"]) {
      expect(html).not.toContain(retired);
    }
  });

  it("does not fetch legacy release catalogs from the promotional page", async () => {
    const script = await readFile(new URL("../../docs/site.js", import.meta.url), "utf8");
    expect(script).not.toContain("download-catalog");
    expect(script).not.toContain("api.github.com/repos");
    expect(script).not.toMatch(/fetch\s*\(/);
  });
});
