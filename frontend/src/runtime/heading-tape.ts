import type { EditionSnapshot } from "./runtime-types";
import { landingPresentation } from "./landing-presentation";
import type { AngularRange } from "./extension-types";

export interface HeadingGuidance {
  readonly target: NonNullable<EditionSnapshot["strikeSelection"]>["target"] | NonNullable<EditionSnapshot["navigation"]>["target"] | undefined;
  readonly window: NonNullable<EditionSnapshot["strike"]>["bombingWindow"];
  readonly relativeDeg: number;
  readonly toleranceDeg: number;
  readonly bandRanges: readonly AngularRange[];
  readonly windowMode?: "impact" | "approach" | "correction";
  readonly color: string;
  readonly text: string;
  readonly ratio: number;
}

export function headingGuidance(snapshot: EditionSnapshot): HeadingGuidance {
  if (snapshot.landing?.settings.enabled) {
    const landing = landingPresentation(snapshot.landing);
    return { target:null,window:null,relativeDeg:0,toleranceDeg:1,bandRanges:[],color:"#8bdddc",ratio:0,
      text:snapshot.landing.geometry ? `${landing.lateral} · ${landing.vertical}` : "降落引导等待数据" };
  }
  const target = snapshot.navigation?.target;
  const relativeDeg = target?.relativeDeg ?? 0;
  const toleranceDeg = headingCdiTolerance(target?.distanceKm ?? 20);
  return { target, window: null, relativeDeg, toleranceDeg, bandRanges: [],
    color: Math.abs(relativeDeg) <= toleranceDeg ? "#f8d66f" : "#ff8e86",
    text: target ? headingGuidanceText(relativeDeg, target.distanceKm) : snapshot.connected ? "选择目标" : "等待 8111",
    ratio: projectHeadingGuidanceRatio(relativeDeg, toleranceDeg) };
}

export interface HeadingTapeMark {
  readonly deltaDeg: number;
  readonly headingDeg: number;
  readonly major: boolean;
  readonly label: string | null;
}

export interface HeadingTapeTargetInput {
  readonly id: string;
  readonly kind: "zone" | "airfield" | "poi" | "traceback" | "hostile";
  readonly label: string;
  readonly relativeDeg: number;
  readonly distanceKm: number;
  readonly isTarget: boolean;
  readonly friendly?: boolean;
  readonly hostile?: boolean;
}

export interface HeadingTapeTargetMarker extends HeadingTapeTargetInput {
  readonly markerLabel: string;
  readonly deltaDeg: number;
  readonly overflow: boolean;
  readonly overlapsZone: boolean;
}

export type HeadingTargetSymbol = "target" | "aircraft" | "brackets" | "traceback" | "diamond";

export function headingTargetSymbol(kind: HeadingTapeTargetInput["kind"]): HeadingTargetSymbol {
  if (kind === "zone") return "target";
  if (kind === "airfield") return "aircraft";
  if (kind === "poi") return "brackets";
  if (kind === "traceback") return "traceback";
  return "diamond";
}

export function headingTapeMarks(headingDeg: number): readonly HeadingTapeMark[] {
  const marks: HeadingTapeMark[] = [];
  for (let delta = -30; delta <= 30; delta += 5) {
    const major = delta % 10 === 0;
    const value = Math.round((headingDeg + delta + 360) % 360);
    marks.push({
      deltaDeg: delta,
      headingDeg: value,
      major,
      label: major && Math.abs(delta) > 10 ? value.toString().padStart(3, "0") : null,
    });
  }
  return marks;
}

export function headingTapeTargetMarkers(
  targets: readonly HeadingTapeTargetInput[],
): readonly HeadingTapeTargetMarker[] {
  const friendlyAirfield = (target: HeadingTapeTargetInput) => target.kind === "airfield" && target.friendly === true && target.hostile !== true;
  const zones = targets.filter((target) => target.kind === "zone");
  const visible = targets.filter((target) => target.isTarget || friendlyAirfield(target) || (
    target.kind !== "hostile" && Math.abs(target.relativeDeg) <= 30
  ));
  const overlappingZones = new Map<string, HeadingTapeTargetInput>();
  for (const target of visible) {
    if (target.kind !== "poi") continue;
    const zone = zones.find((candidate) =>
      Math.abs(candidate.relativeDeg - target.relativeDeg) <= 1
      && Math.abs(candidate.distanceKm - target.distanceKm) <= .5);
    if (zone) overlappingZones.set(target.id, zone);
  }
  const consumedZoneIds = new Set([...overlappingZones.values()].map((zone) => zone.id));
  return visible
    .filter((target) => !consumedZoneIds.has(target.id))
    .map((target) => {
      const overlappingZone = overlappingZones.get(target.id);
      return overlappingZone ? Object.freeze({ ...target, isTarget: target.isTarget || overlappingZone.isTarget }) : target;
    })
    .sort((left, right) => Number(right.isTarget) - Number(left.isTarget)
      || Number(friendlyAirfield(right)) - Number(friendlyAirfield(left))
      || Math.abs(left.relativeDeg) - Math.abs(right.relativeDeg)
      || left.distanceKm - right.distanceKm)
    .slice(0, 6)
    .map((target) => {
      const overlappingZone = overlappingZones.get(target.id);
      return Object.freeze({
        ...target,
        markerLabel: overlappingZone ? `${compactTargetLabel(overlappingZone)}+POI` : compactTargetLabel(target),
        deltaDeg: Math.max(-29, Math.min(29, target.relativeDeg)),
        overflow: Math.abs(target.relativeDeg) > 30,
        overlapsZone: Boolean(overlappingZone),
      });
    });
}

export function headingTapeScale(distanceKm: number): number {
  if (!Number.isFinite(distanceKm) || distanceKm >= 15) return 1;
  if (distanceKm <= 3) return 4;
  return 1 + (15 - distanceKm) / 12 * 3;
}

export function headingCdiTolerance(distanceKm: number): number {
  for (const [limit, tolerance] of [
    [2, 0.5], [5, 1], [8, 2], [12, 3], [20, 5], [35, 8],
  ] as const) if (distanceKm < limit) return tolerance;
  return 12;
}

export function projectHeadingGuidanceRatio(relativeDeg: number, toleranceDeg: number): number {
  if (!Number.isFinite(relativeDeg) || !Number.isFinite(toleranceDeg)) return 0;
  const tolerance = Math.max(0.1, toleranceDeg);
  const magnitude = Math.min(1, Math.abs(relativeDeg) / tolerance) ** 0.62;
  return magnitude ? Math.sign(relativeDeg) * magnitude : 0;
}

export function headingGuidanceText(relativeDeg: number, distanceKm: number): string {
  const absolute = Math.abs(relativeDeg);
  const distance = distanceKm > 0 ? ` · ${distanceKm.toFixed(1)}km` : "";
  if (absolute < 0.05) return `已对准${distance}`;
  const direction = relativeDeg < 0 ? "左" : "右";
  const angle = absolute < 1 ? `${absolute.toFixed(2)}°` : `${absolute.toFixed(1)}°`;
  if (absolute < 0.3) return `精确·${direction}${angle}${distance}`;
  return `${direction}${absolute <= headingCdiTolerance(distanceKm) ? "修" : "转"}${angle}${distance}`;
}

function compactTargetLabel(target: HeadingTapeTargetInput): string {
  if (/^\d+[跑油停居]$/.test(target.label)) return target.label;
  const module = target.label.match(/机场\s*(\d+)\s*·\s*(跑道|油库|停机|生活)/);
  if (module) {
    const glyph = { 跑道: "跑", 油库: "油", 停机: "停", 生活: "居" }[module[2]!];
    return `${module[1]}${glyph}`;
  }
  const ordinal = (target.kind === "zone" ? target.label.match(/(\d+)/)?.[1] : null)
    ?? target.id.match(/(\d+)(?:\D*)$/)?.[1]
    ?? target.label.match(/(\d+)/)?.[1]
    ?? "";
  if (target.kind === "airfield") return `场${ordinal || ""}`;
  if (target.kind === "zone") return `战区${ordinal || ""}`;
  if (target.kind === "poi") return "POI";
  if (target.kind === "traceback") return "返";
  return "敌";
}
