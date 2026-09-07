import { describe, expect, it } from "vitest";
import { applyTheme, readTheme, saveTheme } from "./theme-preference";

class MemoryStorage {
  readonly values = new Map<string, string>();
  getItem(key: string): string | null { return this.values.get(key) ?? null; }
  setItem(key: string, value: string): void { this.values.set(key, value); }
}

describe("Web theme preference", () => {
  it("defaults safely and persists the classic dark theme", () => {
    const storage = new MemoryStorage();
    expect(readTheme(storage)).toBe("glacier");
    saveTheme("classic-dark", storage);
    expect(readTheme(storage)).toBe("classic-dark");
    storage.setItem("bomana:web:theme:v1", "invalid");
    expect(readTheme(storage)).toBe("glacier");
  });

  it("projects the selected theme onto the document root", () => {
    const root = { dataset: {} as DOMStringMap };
    applyTheme("classic-dark", root);
    expect(root.dataset.theme).toBe("classic-dark");
  });
});
