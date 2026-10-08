import type { EditionSnapshot, FriendlyAircraft, NavigationItem } from "./runtime-types";

export interface AirContact {
  readonly item: NavigationItem;
  readonly eastM: number;
  readonly southM: number;
  readonly distanceKm: number;
  readonly relativeDeg: number;
  readonly clock: number;
}

/** Current 2-D observations only; motion annotations never add past contacts. */
export function airRealisticSituation(snapshot: EditionSnapshot, radiusKm: number, nowMs = snapshot.sampledAtMs) {
  const navigation = snapshot.navigation;
  const player = navigation?.player;
  const scale = navigation?.mapScaleM;
  const ageMs = Math.max(0, nowMs - (snapshot.mapObjectsSampledAtMs ?? snapshot.sampledAtMs));
  const positioned = Boolean(player && Number.isFinite(player.x) && Number.isFinite(player.y)
    && scale?.every(value => Number.isFinite(value) && value > 0));
  const available = snapshot.connected && positioned && ageMs <= 3_000;
  const contactsCurrent = available && ageMs <= 1_500 && snapshot.mapObjectsFresh === true;
  const contacts: AirContact[] = [];
  const airports: AirContact[] = [];
  const zones: AirContact[] = [];
  const teammates: { item: FriendlyAircraft; eastM: number; southM: number }[] = [];
  if (contactsCurrent && player && scale) for (const item of navigation?.friendlyAircraft ?? []) {
    if (Number.isFinite(item.x) && Number.isFinite(item.y)) teammates.push({ item,
      eastM: (item.x - player.x) * scale[0], southM: (item.y - player.y) * scale[1] });
  }
  const items = navigation?.aircraftObservations
    ? [...navigation.items.filter(item => !item.aircraft), ...navigation.aircraftObservations] : navigation?.items ?? [];
  if (available && player && scale) for (const item of items) {
    if (!Number.isFinite(item.x) || !Number.isFinite(item.y)) continue;
    const enemy = contactsCurrent && item.kind === "hostile" && item.aircraft === true && item.hostile && !item.friendly;
    const airport = item.kind === "airfield" && item.friendly && !item.hostile;
    const zone = contactsCurrent && item.kind === "zone";
    if (!enemy && !airport && !zone) continue;
    const eastM = (item.x - player.x) * scale[0], southM = (item.y - player.y) * scale[1];
    const relativeDeg = (Math.atan2(eastM, -southM) * 180 / Math.PI - snapshot.flight.headingDeg + 540) % 360 - 180;
    const contact = { item, eastM, southM, distanceKm: Math.hypot(eastM, southM) / 1000,
      relativeDeg, clock: (Math.round((relativeDeg + 360) / 30) % 12) || 12 };
    (enemy ? contacts : zone ? zones : airports).push(contact);
  }
  contacts.sort((a, b) => a.distanceKm - b.distanceKm);
  airports.sort((a, b) => a.distanceKm - b.distanceKm);
  return { available, ageMs, contactsCurrent, delayed: available && !contactsCurrent, contacts, teammates, zones,
    nearby: contacts.filter(contact => contact.distanceKm <= radiusKm), airports,
    reason: !snapshot.connected ? "遥测未连接" : !positioned ? "等待自机位置 / 地图比例" : ageMs > 3_000 ? "地图数据已过期" : "" };
}

/** Metric coordinates before rotation keep distances correct on non-square maps. */
export function airMapOffset(eastM: number, southM: number, headingDeg: number, headingUp: boolean) {
  const angle = (headingUp ? headingDeg : 0) * Math.PI / 180;
  return { x: eastM * Math.cos(angle) + southM * Math.sin(angle), y: -eastM * Math.sin(angle) + southM * Math.cos(angle) };
}

/** Official dx/dy describe direction, not speed or normalized map displacement. */
export function airMapAircraftAngle(item: Pick<NavigationItem, "dx" | "dy">,
  velocity: { eastMps: number; southMps: number } | null | undefined, headingDeg: number, headingUp: boolean): number | null {
  let east = item.dx, south = item.dy;
  if (east == null || south == null || !Number.isFinite(east) || !Number.isFinite(south) || Math.hypot(east, south) < 1e-6) {
    if (!velocity || !Number.isFinite(velocity.eastMps) || !Number.isFinite(velocity.southMps)
      || Math.hypot(velocity.eastMps, velocity.southMps) < 10) return null;
    east = velocity.eastMps; south = velocity.southMps;
  }
  const offset = airMapOffset(east, south, headingDeg, headingUp);
  return Math.atan2(offset.x, -offset.y);
}

/** Intersect the centre-to-contact ray with the inset rectangular map boundary. */
export function airMapMarker(x: number, y: number, halfWidth: number, halfHeight: number) {
  const factor = Math.min(1, halfWidth / Math.max(Math.abs(x), .001), halfHeight / Math.max(Math.abs(y), .001));
  return { x: x * factor, y: y * factor, outside: factor < 1, angle: Math.atan2(y, x) };
}

/** Equally spaced metric rings use exactly the basemap's current eased scale. */
export function airMapRings(pixelsPerMetre: number, maxRadiusPx: number) {
  const maximumM = maxRadiusPx / pixelsPerMetre;
  const desiredStep = maximumM / 3;
  const power = 10 ** Math.floor(Math.log10(desiredStep));
  const step = ([5, 2, 1].find(value => value * power <= desiredStep) ?? 1) * power;
  return Array.from({ length: Math.floor(maximumM / step) }, (_, index) => {
    const metres = step * (index + 1);
    return { radiusPx: metres * pixelsPerMetre, label: metres >= 1000 ? `${Number((metres / 1000).toFixed(1))} km` : `${Math.round(metres)} m` };
  });
}

/** Stores only view scale, never past enemy positions. Near contacts own the
 * readable map; distant contacts retain current-frame edge arrows. */
export class AirMapAutoRange {
  #range = 5;
  #target = 5;
  #lastAt: number | null = null;
  #shrinkSince: number | null = null;

  update(distancesKm: readonly number[], current: boolean, atMs: number): number {
    const dt = this.#lastAt === null ? 0 : Math.max(0, Math.min(250, atMs - this.#lastAt));
    this.#lastAt = atMs;
    if (current && distancesKm.length) {
      const closest = [...distancesKm].sort((a, b) => a - b).slice(0, 3);
      const desired = Math.max(2, Math.min(20, closest[closest.length - 1]! * 1.3));
      if (desired > this.#target * 1.08) {
        this.#target = desired; this.#shrinkSince = null;
      } else if (desired < this.#target * .75) {
        this.#shrinkSince ??= atMs;
        if (atMs - this.#shrinkSince >= 3000) this.#target = desired;
      } else this.#shrinkSince = null;
    } else {
      // Empty/failed frames remove contacts, but must not make the map pump.
      this.#shrinkSince = null;
      this.#target = this.#range;
    }
    const tau = this.#target > this.#range ? 350 : 1200;
    this.#range += (this.#target - this.#range) * (1 - Math.exp(-dt / tau));
    return this.#range;
  }
}
