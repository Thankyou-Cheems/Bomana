const STORAGE_KEY = "bomana:web:pip-risk-consent:v1";

export class PipRiskConsentStore {
  readonly #storage: Storage | null;
  #sessionAccepted = false;

  constructor(storage: Storage | null = safeLocalStorage()) {
    this.#storage = storage;
  }

  accepted(): boolean {
    if (this.#sessionAccepted) return true;
    try { return this.#storage?.getItem(STORAGE_KEY) === "accepted"; } catch { return false; }
  }

  accept(persist: boolean): void {
    this.#sessionAccepted = true;
    if (!persist) return;
    try { this.#storage?.setItem(STORAGE_KEY, "accepted"); } catch { /* Session consent remains valid. */ }
  }
}

function safeLocalStorage(): Storage | null {
  try { return globalThis.localStorage ?? null; } catch { return null; }
}
