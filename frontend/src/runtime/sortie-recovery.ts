import { normalizeOfficialMapInfo } from "./map-info";

export const RESET_UNDO_WINDOW_MS = 30_000;
const SORTIE_RESUME_WINDOW_MS = 15 * 60_000;

export type SortieResetReason = "aircraft-loss" | "telemetry-timeout";

export interface SortieRestorePoint {
  readonly savedAtMs: number;
  readonly mapSignature: string;
  readonly phase: "alive" | "loss-pending";
  readonly lifeStartedAtMs: number;
  readonly lifeIndex: number;
  readonly cycleSeconds: number;
  readonly selectedNavigationId: string | null;
  readonly navigationSelectionMode: "auto" | "locked" | "paused";
  readonly manualPoi: { readonly x: number; readonly y: number } | null;
  readonly strikeTargetPoint: { readonly x: number; readonly y: number; readonly label: string } | null;
  readonly checklistChecked: readonly boolean[];
  readonly resetSuppressedUntilEvidence: boolean;
}

export interface SortieResetUndoRecord {
  readonly reason: SortieResetReason;
  readonly createdAtMs: number;
  readonly expiresAtMs: number;
  readonly restore: SortieRestorePoint;
}

export interface SortieRecoveryRecord {
  readonly schemaVersion: 1;
  readonly resume: SortieRestorePoint | null;
  readonly resetUndo: SortieResetUndoRecord | null;
}

export interface SortieRecoveryStore {
  load(nowMs: number, expectedCycleSeconds: number): SortieRecoveryRecord | null;
  save(record: SortieRecoveryRecord): void;
  clear(): void;
}

export class MemorySortieRecoveryStore implements SortieRecoveryStore {
  value: unknown = null;
  load(nowMs: number, expectedCycleSeconds: number): SortieRecoveryRecord | null {
    const record = normalizeSortieRecoveryRecord(structuredClone(this.value), nowMs, expectedCycleSeconds);
    if (this.value !== null && !record) this.value = null;
    return record;
  }
  save(record: SortieRecoveryRecord): void { this.value = structuredClone(record); }
  clear(): void { this.value = null; }
}

export class BrowserSortieRecoveryStore implements SortieRecoveryStore {
  readonly #key: string;
  readonly #storage: Storage;
  constructor(channel: string, storage: Storage = localStorage) {
    this.#key = `bomana:sortie-recovery:v1:${channel}`;
    this.#storage = storage;
  }
  load(nowMs: number, expectedCycleSeconds: number): SortieRecoveryRecord | null {
    try {
      const raw = this.#storage.getItem(this.#key);
      if (!raw) return null;
      const record = normalizeSortieRecoveryRecord(JSON.parse(raw), nowMs, expectedCycleSeconds);
      if (!record) this.#storage.removeItem(this.#key);
      return record;
    } catch {
      try { this.#storage.removeItem(this.#key); } catch { /* Private storage may be unavailable. */ }
      return null;
    }
  }
  save(record: SortieRecoveryRecord): void {
    try { this.#storage.setItem(this.#key, JSON.stringify(record)); } catch { /* Recovery remains best-effort. */ }
  }
  clear(): void {
    try { this.#storage.removeItem(this.#key); } catch { /* Private storage may be unavailable. */ }
  }
}

export function sortieMapSignature(mapInfo: Readonly<Record<string, unknown>> | null): string | null {
  const bounds = normalizeOfficialMapInfo(mapInfo);
  if (!bounds) return null;
  const gridZero = Array.isArray(mapInfo?.grid_zero) ? mapInfo.grid_zero.slice(0, 2) : [];
  const gridSteps = Array.isArray(mapInfo?.grid_steps) ? mapInfo.grid_steps.slice(0, 2) : [];
  return JSON.stringify([bounds.minimum, bounds.maximum, gridZero, gridSteps]);
}

function normalizeSortieRecoveryRecord(
  value: unknown,
  nowMs: number,
  expectedCycleSeconds: number,
): SortieRecoveryRecord | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Partial<SortieRecoveryRecord>;
  if (record.schemaVersion !== 1) return null;
  const resume = normalizeSortieRestorePoint(record.resume, nowMs, expectedCycleSeconds);
  let resetUndo: SortieResetUndoRecord | null = null;
  if (record.resetUndo && typeof record.resetUndo === "object" && !Array.isArray(record.resetUndo)) {
    const candidate = record.resetUndo as Partial<SortieResetUndoRecord>;
    const restore = normalizeSortieRestorePoint(candidate.restore, nowMs, expectedCycleSeconds);
    if (
      (candidate.reason === "aircraft-loss" || candidate.reason === "telemetry-timeout")
      && Number.isFinite(candidate.createdAtMs)
      && Number.isFinite(candidate.expiresAtMs)
      && candidate.expiresAtMs! > nowMs
      && candidate.expiresAtMs! - candidate.createdAtMs! === RESET_UNDO_WINDOW_MS
      && restore
    ) {
      resetUndo = Object.freeze({
        reason: candidate.reason,
        createdAtMs: candidate.createdAtMs!,
        expiresAtMs: candidate.expiresAtMs!,
        restore,
      });
    }
  }
  return resume || resetUndo ? Object.freeze({ schemaVersion: 1, resume, resetUndo }) : null;
}

function normalizeSortieRestorePoint(
  value: unknown,
  nowMs: number,
  expectedCycleSeconds: number,
): SortieRestorePoint | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const restore = value as Partial<SortieRestorePoint>;
  if (
    !Number.isFinite(restore.savedAtMs)
    || nowMs < restore.savedAtMs!
    || nowMs - restore.savedAtMs! > SORTIE_RESUME_WINDOW_MS
    || typeof restore.mapSignature !== "string"
    || restore.mapSignature.length < 8
    || restore.mapSignature.length > 512
    || (restore.phase !== "alive" && restore.phase !== "loss-pending")
    || !Number.isFinite(restore.lifeStartedAtMs)
    || restore.lifeStartedAtMs! > restore.savedAtMs!
    || !Number.isInteger(restore.lifeIndex)
    || restore.lifeIndex! < 1
    || restore.cycleSeconds !== expectedCycleSeconds
    || !Array.isArray(restore.checklistChecked)
    || restore.checklistChecked.length > 64
    || !restore.checklistChecked.every((item) => typeof item === "boolean")
    || (restore.navigationSelectionMode !== "auto" && restore.navigationSelectionMode !== "locked" && restore.navigationSelectionMode !== "paused")
  ) return null;
  const manualPoi = normalizeStoredPoint(restore.manualPoi);
  const strikeTargetPoint = normalizeStoredTargetPoint(restore.strikeTargetPoint);
  if ((restore.manualPoi && !manualPoi) || (restore.strikeTargetPoint && !strikeTargetPoint)) return null;
  return Object.freeze({
    savedAtMs: restore.savedAtMs!,
    mapSignature: restore.mapSignature,
    phase: restore.phase,
    lifeStartedAtMs: restore.lifeStartedAtMs!,
    lifeIndex: restore.lifeIndex!,
    cycleSeconds: expectedCycleSeconds,
    selectedNavigationId: typeof restore.selectedNavigationId === "string" && restore.selectedNavigationId.length <= 160
      ? restore.selectedNavigationId
      : null,
    navigationSelectionMode: restore.navigationSelectionMode,
    manualPoi,
    strikeTargetPoint,
    checklistChecked: Object.freeze([...restore.checklistChecked]),
    resetSuppressedUntilEvidence: restore.resetSuppressedUntilEvidence === true,
  });
}

function normalizeStoredPoint(value: unknown): { readonly x: number; readonly y: number } | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const point = value as { readonly x?: unknown; readonly y?: unknown };
  return typeof point.x === "number" && Number.isFinite(point.x) && point.x >= 0 && point.x <= 1
    && typeof point.y === "number" && Number.isFinite(point.y) && point.y >= 0 && point.y <= 1
    ? Object.freeze({ x: point.x, y: point.y })
    : null;
}

function normalizeStoredTargetPoint(value: unknown): { readonly x: number; readonly y: number; readonly label: string } | null {
  const point = normalizeStoredPoint(value);
  if (!point || !value || typeof value !== "object" || Array.isArray(value)) return null;
  const label = (value as { readonly label?: unknown }).label;
  return typeof label === "string" && label.length <= 120
    ? Object.freeze({ ...point, label })
    : null;
}
