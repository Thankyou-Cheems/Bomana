export type PublicEdition = "Lite" | "Standard";

export interface PublicFrame {
  readonly sampledAtMs: number;
  readonly connected: boolean;
  readonly indicators: Readonly<Record<string, unknown>> | null;
  readonly state: Readonly<Record<string, unknown>> | null;
  readonly mapObjects: readonly unknown[] | null;
  readonly mapInfo: Readonly<Record<string, unknown>> | null;
}

export interface NavigationTarget {
  readonly id: string;
  readonly kind: "zone" | "airfield";
  readonly label: string;
  readonly x: number;
  readonly y: number;
  readonly bearingDeg: number;
  readonly distanceKm: number;
  readonly relativeDeg: number;
  readonly friendly: boolean;
}

export interface PublicSnapshot {
  readonly edition: PublicEdition;
  readonly connected: boolean;
  readonly remainingSec: number | null;
  readonly progress: number;
  readonly cycle: number | null;
  readonly flight: {
    readonly iasKmh: number;
    readonly altitudeM: number;
    readonly headingDeg: number;
    readonly fuelKg: number;
  } | null;
  readonly player: { readonly x: number; readonly y: number } | null;
  readonly targets: readonly NavigationTarget[];
  readonly target: NavigationTarget | null;
}

export class PublicRuntime {
  readonly #edition: PublicEdition;
  #cycleSeconds: number;
  #lifeStartedAtMs: number | null = null;
  #alive = false;
  #selectedTargetId: string | null = null;
  #snapshot: PublicSnapshot;

  constructor(edition: PublicEdition, cycleMinutes = 15) {
    this.#edition = edition;
    this.#cycleSeconds = normalizeCycle(cycleMinutes) * 60;
    this.#snapshot = emptySnapshot(edition);
  }

  setCycleMinutes(value: number): void {
    this.#cycleSeconds = normalizeCycle(value) * 60;
  }

  resetTimer(nowMs: number): void {
    this.#lifeStartedAtMs = nowMs;
    this.#alive = true;
  }

  cycleTarget(): void {
    const targets = this.#snapshot.targets;
    if (!targets.length) return;
    const current = targets.findIndex((target) => target.id === this.#selectedTargetId);
    this.#selectedTargetId = targets[(current + 1 + targets.length) % targets.length]!.id;
    this.#snapshot = { ...this.#snapshot, target: targets.find((target) => target.id === this.#selectedTargetId) ?? null };
  }

  ingest(frame: PublicFrame): PublicSnapshot {
    const flight = parseFlight(frame.indicators, frame.state);
    const alive = Boolean(frame.connected && flight);
    if (alive && !this.#alive) this.#lifeStartedAtMs = frame.sampledAtMs;
    this.#alive = alive;
    const elapsedSec = this.#lifeStartedAtMs === null ? null : Math.max(0, (frame.sampledAtMs - this.#lifeStartedAtMs) / 1000);
    const timer = elapsedSec === null
      ? { remainingSec: null, progress: 0, cycle: null }
      : {
          remainingSec: this.#cycleSeconds - elapsedSec % this.#cycleSeconds,
          progress: elapsedSec % this.#cycleSeconds / this.#cycleSeconds,
          cycle: Math.floor(elapsedSec / this.#cycleSeconds) + 1,
        };
    const navigation = this.#edition === "Standard"
      ? buildNavigation(frame.mapObjects, frame.mapInfo, flight?.headingDeg ?? 0)
      : { player: null, targets: [] as readonly NavigationTarget[] };
    if (this.#selectedTargetId && !navigation.targets.some((target) => target.id === this.#selectedTargetId)) {
      this.#selectedTargetId = null;
    }
    const target = this.#selectedTargetId
      ? navigation.targets.find((item) => item.id === this.#selectedTargetId) ?? null
      : navigation.targets.find((item) => Math.abs(item.relativeDeg) <= 45) ?? navigation.targets[0] ?? null;
    this.#selectedTargetId = target?.id ?? null;
    this.#snapshot = Object.freeze({
      edition: this.#edition,
      connected: frame.connected,
      ...timer,
      flight: this.#edition === "Standard" ? flight : null,
      player: navigation.player,
      targets: Object.freeze([...navigation.targets]),
      target,
    });
    return this.#snapshot;
  }

  snapshot(): PublicSnapshot { return this.#snapshot; }
}

function parseFlight(indicators: PublicFrame["indicators"], state: PublicFrame["state"]): PublicSnapshot["flight"] {
  if (indicators?.valid !== true || !state) return null;
  const iasKmh = finite(state["IAS, km/h"]);
  const altitudeM = finite(state["H, m"]);
  const fuelKg = finite(state["Mfuel, kg"]);
  const headingDeg = finite(indicators.compass1 ?? indicators.compass);
  if (iasKmh === null || altitudeM === null || headingDeg === null) return null;
  return Object.freeze({ iasKmh, altitudeM, headingDeg: normalizeHeading(headingDeg), fuelKg: fuelKg ?? 0 });
}

function buildNavigation(
  value: PublicFrame["mapObjects"],
  mapInfo: PublicFrame["mapInfo"],
  headingDeg: number,
): { readonly player: { readonly x: number; readonly y: number } | null; readonly targets: readonly NavigationTarget[] } {
  if (!Array.isArray(value)) return { player: null, targets: [] };
  const playerRecord = value.find((item) => record(item)?.type === "player");
  const player = point(record(playerRecord));
  const scale = mapScale(mapInfo);
  if (!player || !scale) return { player: null, targets: [] };
  const targets = value.flatMap((item, index) => {
    const source = record(item);
    if (!source) return [];
    const kind = source.type === "bombing_point" ? "zone" : source.type === "airfield" ? "airfield" : null;
    if (!kind) return [];
    const position = kind === "airfield" ? airfieldCenter(source) : point(source);
    if (!position) return [];
    const dxM = (position.x - player.x) * scale.x;
    const dyM = (position.y - player.y) * scale.y;
    const bearingDeg = normalizeHeading(Math.atan2(dxM, -dyM) * 180 / Math.PI);
    const relativeDeg = normalizeRelative(bearingDeg - headingDeg);
    return [Object.freeze({
      id: `${kind}:${index}`,
      kind,
      label: kind === "zone" ? `战区 ${index + 1}` : `${friendly(source) ? "友方" : "敌方"}机场`,
      x: position.x,
      y: position.y,
      bearingDeg,
      distanceKm: Math.hypot(dxM, dyM) / 1000,
      relativeDeg,
      friendly: friendly(source),
    }) satisfies NavigationTarget];
  }).sort((left, right) => left.distanceKm - right.distanceKm);
  return { player: Object.freeze(player), targets: Object.freeze(targets) };
}

function record(value: unknown): Readonly<Record<string, unknown>> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Readonly<Record<string, unknown>> : null;
}

function point(value: Readonly<Record<string, unknown>> | null): { x: number; y: number } | null {
  const x = finite(value?.x);
  const y = finite(value?.y);
  return x !== null && y !== null ? { x, y } : null;
}

function airfieldCenter(value: Readonly<Record<string, unknown>>): { x: number; y: number } | null {
  const sx = finite(value.sx); const sy = finite(value.sy); const ex = finite(value.ex); const ey = finite(value.ey);
  return sx !== null && sy !== null && ex !== null && ey !== null ? { x: (sx + ex) / 2, y: (sy + ey) / 2 } : null;
}

function mapScale(value: PublicFrame["mapInfo"]): { x: number; y: number } | null {
  const minimum = Array.isArray(value?.map_min) ? value.map_min : null;
  const maximum = Array.isArray(value?.map_max) ? value.map_max : null;
  const x = finite(maximum?.[0])! - finite(minimum?.[0])!;
  const y = finite(maximum?.[1])! - finite(minimum?.[1])!;
  return Number.isFinite(x) && Number.isFinite(y) && x > 0 && y > 0 ? { x, y } : null;
}

function friendly(value: Readonly<Record<string, unknown>>): boolean {
  if (value.side === "friendly") return true;
  const color = String(value.color ?? "").toLowerCase();
  return color.includes("174dff") || color.includes("blue");
}

function normalizeCycle(value: number): number { return Number.isInteger(value) && value >= 1 && value <= 180 ? value : 15; }
function normalizeHeading(value: number): number { return (value % 360 + 360) % 360; }
function normalizeRelative(value: number): number { return (value + 540) % 360 - 180; }
function finite(value: unknown): number | null { return typeof value === "number" && Number.isFinite(value) ? value : null; }

function emptySnapshot(edition: PublicEdition): PublicSnapshot {
  return Object.freeze({ edition, connected: false, remainingSec: null, progress: 0, cycle: null, flight: null, player: null, targets: [], target: null });
}
