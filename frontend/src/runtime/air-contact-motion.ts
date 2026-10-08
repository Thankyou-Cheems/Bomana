import type { EditionSnapshot } from "./runtime-types";
import type { AirContact } from "./air-realistic-model";

type Velocity = { eastMps: number; southMps: number };
type Observation = { x: number; y: number; role: string };
type MotionSample = { at: number; x: number; y: number; eastM: number; southM: number };
type TrailSample = { at: number; x: number; y: number };
type Track = Observation & {
  samples: MotionSample[];
  trail: TrailSample[];
  since: number;
  velocity: Velocity | null;
  relativeVelocity: Velocity | null;
  groupSince: number | null;
};
export interface AirContactTrailPoint {
  readonly eastM: number;
  readonly southM: number;
  readonly ageMs: number;
}
export interface AirContactMotion {
  readonly velocity: Velocity | null;
  /** Horizontal ground speed; map observations cannot measure TAS or IAS. */
  readonly groundSpeedMps: number | null;
  /** Positive means decreasing horizontal separation, negative means opening. */
  readonly closingMps: number | null;
  /** Horizontal relative velocity of this contact, including ownship motion. */
  readonly relativeVelocity: Velocity | null;
  /** World positions over the last few seconds, relative to the current ownship. */
  readonly trail: readonly AirContactTrailPoint[];
  /** A sustained slow formation heuristic, never a controller identity. */
  readonly suspectedGroup: boolean;
  readonly groupSize: number;
}
const UNKNOWN: AirContactMotion = { velocity: null, groundSpeedMps: null, closingMps: null, relativeVelocity: null, trail: [], suspectedGroup: false, groupSize: 0 };
export const AIR_CONTACT_TRAIL_MS = 6000;
const MAX_SPEED_MPS = 900;

/** Short-lived position differences for currently visible contacts only.
 * Array IDs and official dx/dy are not stable identities or measured speeds.
 * Trails and closure are horizontal geometry, not a lock or weapon solution. */
export class AirContactMotionEstimator {
  #key = "";
  #at = -Infinity;
  #tracks: Track[] = [];
  #result: AirContactMotion[] = [];
  #byPosition = new Map<string, AirContactMotion>();

  reset(): void { this.#at = -Infinity; this.#tracks = []; this.#result = []; this.#byPosition.clear(); }

  observe(snapshot: EditionSnapshot, contacts: readonly AirContact[], current: boolean): readonly AirContactMotion[] {
    const scale = snapshot.navigation?.mapScaleM;
    const at = snapshot.mapObjectsSampledAtMs;
    if (!current || !scale || !Number.isFinite(at) || !contacts.length) {
      this.reset(); return contacts.map(() => UNKNOWN);
    }
    const time = at!;
    const key = JSON.stringify([scale, snapshot.mapGrid, snapshot.timer.lifeIndex, snapshot.flight.aircraft]);
    if (key !== this.#key || time < this.#at || time - this.#at > 1500) this.reset();
    this.#key = key;
    const points = contacts.map(({ item }) => ({ x: item.x * scale[0], y: item.y * scale[1], role: item.officialIcon?.trim().toLowerCase() ?? "" }));
    // Ownship updates may reorder distance-sorted contacts without a new map
    // observation. Keep vectors attached to positions, never to row indices.
    if (time === this.#at) return points.map(point => this.#byPosition.get(positionKey(point)) ?? UNKNOWN);
    const dt = (time - this.#at) / 1000;
    const previous = this.#tracks;
    const candidates = points.map(point => previous.map((track, index) => {
      const displacement = Math.hypot(point.x - track.x, point.y - track.y);
      const error = Math.hypot(point.x - track.x - (track.velocity?.eastMps ?? 0) * dt,
        point.y - track.y - (track.velocity?.southMps ?? 0) * dt);
      return { index, error: point.role === track.role && displacement <= MAX_SPEED_MPS * dt + 20 ? error : Infinity };
    }).filter(pair => Number.isFinite(pair.error)).sort((a, b) => a.error - b.error));
    const successors = previous.map(() => [] as { index: number; error: number }[]);
    candidates.forEach((list, index) => list.forEach(pair => successors[pair.index]!.push({ index, error: pair.error })));
    successors.forEach(list => list.sort((a, b) => a.error - b.error));
    this.#tracks = points.map((point, index) => {
      const contact = contacts[index]!;
      const sample: MotionSample = { ...point, at: time, eastM: contact.eastM, southM: contact.southM };
      const fresh = (): Track => ({ ...point, samples: [sample], trail: [{ at: time, x: point.x, y: point.y }], since: time, velocity: null, relativeVelocity: null, groupSince: null });
      const [best, second] = candidates[index]!;
      if (!best || second && second.error < best.error * 1.6 + 20) return fresh();
      // A previous contact must have one unambiguous successor as well.
      const [successor, rival] = successors[best.index]!;
      if (successor?.index !== index || rival && rival.error < best.error * 1.6 + 20) return fresh();
      const track = previous[best.index]!;
      let velocity = track.velocity;
      let relativeVelocity = track.relativeVelocity;
      const samples = [...track.samples.filter(row => time - row.at <= 1500), sample];
      const trail = [...track.trail.filter(row => time - row.at <= AIR_CONTACT_TRAIL_MS), { at: time, x: point.x, y: point.y }];
      if (time - samples[0]!.at >= 750) {
        const fit = fitMotion(samples);
        if (Math.hypot(fit.absolute.eastMps, fit.absolute.southMps) > MAX_SPEED_MPS) return fresh();
        const weight = 1 - Math.exp(-dt / .65);
        velocity = smoothVelocity(velocity, fit.absolute, weight);
        // Ownship and enemy use the same observed interval. TAS, heading and
        // screen motion (including auto zoom) are not radial velocity inputs.
        const ownSpeed = Math.hypot(fit.absolute.eastMps - fit.relative.eastMps, fit.absolute.southMps - fit.relative.southMps);
        relativeVelocity = ownSpeed <= MAX_SPEED_MPS ? smoothVelocity(relativeVelocity, fit.relative, weight) : null;
      }
      return { ...track, ...point, samples, trail, velocity, relativeVelocity };
    });
    this.#at = time;
    const ownX = snapshot.navigation!.player!.x * scale[0];
    const ownY = snapshot.navigation!.player!.y * scale[1];
    const groups = slowFormations(this.#tracks, time);
    for (const [index, track] of this.#tracks.entries()) {
      track.groupSince = groups.some(group => group.includes(index)) ? track.groupSince ?? time : null;
    }
    this.#result = this.#tracks.map((track, index) => {
      const { eastM, southM } = contacts[index]!;
      return { velocity: track.velocity, groundSpeedMps: track.velocity ? Math.hypot(track.velocity.eastMps, track.velocity.southMps) : null,
        closingMps: lineClosing(track.relativeVelocity, eastM, southM), relativeVelocity: track.relativeVelocity,
        trail: track.trail.map(row => ({ eastM: row.x - ownX, southM: row.y - ownY, ageMs: time - row.at })),
        suspectedGroup: false, groupSize: 0 };
    });
    for (const group of groups) {
      if (group.some(index => time - (this.#tracks[index]!.groupSince ?? time) < 6000)) continue;
      for (const index of group) this.#result[index] = { ...this.#result[index]!, suspectedGroup: true,
        groupSize: index === group[0] ? group.length : 0 };
    }
    this.#byPosition = new Map(points.map((point, index) => [positionKey(point), this.#result[index]!]));
    return this.#result;
  }
}

function positionKey(point: Observation): string { return `${point.x}:${point.y}:${point.role}`; }

function lineClosing(relative: Velocity | null, eastM: number, southM: number): number | null {
  const distanceM = Math.hypot(eastM, southM);
  return relative && distanceM > 1 ? -(relative.eastMps * eastM + relative.southMps * southM) / distanceM : null;
}

function smoothVelocity(previous: Velocity | null, measured: Velocity, weight: number): Velocity {
  return previous ? { eastMps: previous.eastMps + (measured.eastMps - previous.eastMps) * weight,
    southMps: previous.southMps + (measured.southMps - previous.southMps) * weight } : measured;
}

/** A short metric least-squares fit damps coordinate quantization without the
 * old 750 ms anchor resets. Only distinct source timestamps enter this fit. */
function fitMotion(samples: readonly MotionSample[]): { absolute: Velocity; relative: Velocity } {
  const meanAt = samples.reduce((sum, row) => sum + row.at, 0) / samples.length;
  let variance = 0, x = 0, y = 0, east = 0, south = 0;
  const origin = samples[0]!;
  for (const row of samples) {
    const seconds = (row.at - meanAt) / 1000;
    variance += seconds ** 2;
    x += seconds * (row.x - origin.x); y += seconds * (row.y - origin.y);
    east += seconds * (row.eastM - origin.eastM); south += seconds * (row.southM - origin.southM);
  }
  return { absolute: { eastMps: x / variance, southMps: y / variance },
    relative: { eastMps: east / variance, southMps: south / variance } };
}

export function airContactClosingLabel(closingMps: number | null): string {
  if (closingMps === null) return "";
  if (Math.abs(closingMps) < 10) return "稳定 ≈0 m/s";
  return `${closingMps > 0 ? "接近" : "远离"} ${Math.round(Math.abs(closingMps) / 10) * 10} m/s`;
}

function slowFormations(tracks: readonly Track[], at: number): number[][] {
  const slow = (track: Track) => track.velocity && at - track.since >= 2000
    && Math.hypot(track.velocity.eastMps, track.velocity.southMps) >= 40
    && Math.hypot(track.velocity.eastMps, track.velocity.southMps) <= 170;
  const compatible = (a: Track, b: Track) => {
    if (Math.hypot(a.x - b.x, a.y - b.y) > 1500) return false;
    if (Math.hypot(a.velocity!.eastMps - b.velocity!.eastMps, a.velocity!.southMps - b.velocity!.southMps) > 25) return false;
    const dot = a.velocity!.eastMps * b.velocity!.eastMps + a.velocity!.southMps * b.velocity!.southMps;
    return dot / (Math.hypot(a.velocity!.eastMps, a.velocity!.southMps) * Math.hypot(b.velocity!.eastMps, b.velocity!.southMps)) >= .94;
  };
  const groups: number[][] = [], visited = new Set<number>();
  for (let i = 0; i < tracks.length; i++) {
    if (visited.has(i) || !slow(tracks[i]!)) continue;
    const group = [i]; visited.add(i);
    for (let cursor = 0; cursor < group.length; cursor++) {
      const a = tracks[group[cursor]!]!;
      for (let j = 0; j < tracks.length; j++) {
        const b = tracks[j]!;
        if (visited.has(j) || !slow(b) || !compatible(a, b)) continue;
        visited.add(j); group.push(j);
      }
    }
    // Chained similarities do not prove that the whole formation is coherent.
    if (group.length >= 3 && group.every(i => group.every(j => compatible(tracks[i]!, tracks[j]!)))) {
      groups.push(group.sort((a, b) => a - b));
    }
  }
  return groups;
}

/** Distance only, not danger, altitude, AI identity or closure rate. */
export function airContactColor(distanceKm: number): string {
  const stops = [[0, 255, 100, 109], [2, 255, 100, 109], [5, 255, 178, 105], [10, 226, 203, 149], [20, 181, 168, 151]];
  const index = stops.findIndex(stop => distanceKm <= stop[0]!);
  const to = stops[index < 0 ? stops.length - 1 : index]!;
  const from = stops[Math.max(0, index - 1)]!;
  const t = index <= 0 ? 1 : (distanceKm - from[0]!) / (to[0]! - from[0]!);
  return `rgb(${[1, 2, 3].map(i => Math.round(from[i]! + (to[i]! - from[i]!) * t)).join(", ")})`;
}
