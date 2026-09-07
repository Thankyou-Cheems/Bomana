import { describe, expect, it } from "vitest";
import { readPipMapVisible, savePipMapVisible } from "./pip-map-preference";

describe("PiP miniature map preference", () => {
  it("shows the map by default and remembers both choices across window reopening", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
    };
    expect(readPipMapVisible("Standard", storage)).toBe(true);
    savePipMapVisible("Standard", false, storage);
    expect(readPipMapVisible("Standard", storage)).toBe(false);
    expect(readPipMapVisible("Enhanced", storage)).toBe(true);
    savePipMapVisible("Standard", true, storage);
    savePipMapVisible("Enhanced", false, storage);
    expect(readPipMapVisible("Standard", storage)).toBe(true);
    expect(readPipMapVisible("Enhanced", storage)).toBe(false);
  });

  it("keeps the window usable when browser storage is blocked", () => {
    const storage = {
      getItem: (): never => { throw new Error("storage blocked"); },
      setItem: (): never => { throw new Error("storage blocked"); },
    };
    expect(readPipMapVisible("Standard", storage)).toBe(true);
    expect(() => savePipMapVisible("Standard", false, storage)).not.toThrow();
  });
});
