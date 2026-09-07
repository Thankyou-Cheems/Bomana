import { describe, expect, it } from "vitest";
import {
  BrowserSortieRecoveryStore,
  MemorySortieRecoveryStore,
  sortieMapSignature,
  type SortieRecoveryRecord,
} from "./sortie-recovery";

class MemoryStorage {
  readonly values = new Map<string, string>();
  getItem(key: string): string | null { return this.values.get(key) ?? null; }
  setItem(key: string, value: string): void { this.values.set(key, value); }
  removeItem(key: string): void { this.values.delete(key); }
}

function record(savedAtMs = 1_000): SortieRecoveryRecord {
  return {
    schemaVersion: 1,
    resume: {
      savedAtMs,
      mapSignature: "[[0,0],[100000,100000],[],[]]",
      phase: "alive",
      lifeStartedAtMs: 0,
      lifeIndex: 1,
      cycleSeconds: 900,
      selectedNavigationId: "zone_0.5000_0.3000",
      navigationSelectionMode: "locked",
      manualPoi: null,
      strikeTargetPoint: null,
      checklistChecked: [true, false],
      resetSuppressedUntilEvidence: false,
    },
    resetUndo: null,
  };
}

describe("Sortie Recovery Store", () => {
  it("round-trips a bounded record and rejects stale or cycle-mismatched state", () => {
    const store = new MemorySortieRecoveryStore();
    store.save(record());
    expect(store.load(14 * 60_000, 900)?.resume?.selectedNavigationId).toBe("zone_0.5000_0.3000");

    store.save(record());
    expect(store.load(15 * 60_000 + 1_001, 900)).toBeNull();
    expect(store.value).toBeNull();

    store.save(record());
    expect(store.load(2_000, 600)).toBeNull();

    const legacy = structuredClone(record()) as unknown as { resume: Record<string, unknown> };
    delete legacy.resume.resetSuppressedUntilEvidence;
    store.value = legacy;
    expect(store.load(2_000, 900)?.resume?.resetSuppressedUntilEvidence).toBe(false);
  });

  it("removes malformed browser state instead of exposing it to Edition Runtime", () => {
    const storage = new MemoryStorage();
    storage.setItem("bomana:sortie-recovery:v1:Standard", "not-json");
    const store = new BrowserSortieRecoveryStore("Standard", storage as unknown as Storage);
    expect(store.load(2_000, 900)).toBeNull();
    expect(storage.values.size).toBe(0);
  });

  it("uses bounded official map facts for the resume signature", () => {
    const first = sortieMapSignature({ valid: true, map_min: [0, 0], map_max: [100_000, 100_000], grid_zero: [0, 0], grid_steps: [10_000, 10_000] });
    const same = sortieMapSignature({ valid: true, map_min: [0, 0], map_max: [100_000, 100_000], grid_zero: [0, 0], grid_steps: [10_000, 10_000], ignored: "value" });
    const different = sortieMapSignature({ valid: true, map_min: [-50_000, -50_000], map_max: [50_000, 50_000] });
    expect(first).toBe(same);
    expect(first).not.toBe(different);
  });
});
