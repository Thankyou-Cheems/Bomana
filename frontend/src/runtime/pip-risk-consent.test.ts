import { describe, expect, it } from "vitest";
import { PipRiskConsentStore } from "./pip-risk-consent";

class MemoryStorage implements Storage {
  readonly values = new Map<string, string>();
  get length(): number { return this.values.size; }
  clear(): void { this.values.clear(); }
  getItem(key: string): string | null { return this.values.get(key) ?? null; }
  key(index: number): string | null { return [...this.values.keys()][index] ?? null; }
  removeItem(key: string): void { this.values.delete(key); }
  setItem(key: string, value: string): void { this.values.set(key, value); }
}

describe("PiP anti-cheat risk consent", () => {
  it("requires explicit consent once per page unless the user persists the choice", () => {
    const storage = new MemoryStorage();
    const consent = new PipRiskConsentStore(storage);
    expect(consent.accepted()).toBe(false);
    consent.accept(false);
    expect(consent.accepted()).toBe(true);
    expect(storage.length).toBe(0);

    const reloaded = new PipRiskConsentStore(storage);
    expect(reloaded.accepted()).toBe(false);
    reloaded.accept(true);
    expect(new PipRiskConsentStore(storage).accepted()).toBe(true);
  });
});
