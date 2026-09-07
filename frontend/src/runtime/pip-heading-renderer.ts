import type { EditionSnapshot } from "./runtime-types";
import {
  headingGuidance,
  headingTapeScale,
  headingTapeTargetMarkers,
  headingTargetSymbol,
  projectHeadingGuidanceRatio,
  type HeadingTapeTargetInput,
  type HeadingTapeTargetMarker,
} from "./heading-tape";
import { SampledAngleMotion, sampledAtPerformanceTime } from "./sampled-angle-motion";

export interface PictureInPictureHeadingLayout {
  readonly visualScale: number;
  readonly degreeFontPx: number;
  readonly tickTop: number;
  readonly degreeTextY: number;
  readonly markerY: number;
  readonly distanceY: number;
  readonly guidanceTop: number;
  readonly guidanceTextY: number;
  readonly guidanceTrackY: number;
}

export function pictureInPictureHeadingLayout(width: number, height: number): PictureInPictureHeadingLayout {
  const visualScale = clamp(Math.min(width / 720, height / 150), 0.72, 2);
  return Object.freeze({
    visualScale,
    degreeFontPx: Math.max(8, 8 * visualScale),
    tickTop: height * 0.05,
    degreeTextY: height * 0.27,
    markerY: height * 0.42,
    distanceY: height * 0.54,
    guidanceTop: height * 0.70,
    guidanceTextY: height * 0.73,
    guidanceTrackY: height * 0.92,
  });
}

export class PictureInPictureHeadingRenderer {
  readonly #guidance: typeof headingGuidance;
  readonly #view: Window;
  readonly #canvas: HTMLCanvasElement;
  #snapshot: EditionSnapshot | null = null;
  #displayHeading = Number.NaN;
  readonly #headingMotion = new SampledAngleMotion();
  #displayGuidance = 0;
  readonly #markerDisplay = new Map<string, SampledAngleMotion>();
  #lastFrameMs = 0;
  #lastObservationMs = 0;
  #frame = 0;
  #targetId = "";
  #extraTargets: readonly HeadingTapeTargetInput[] = [];

  constructor(options: { readonly view: Window; readonly canvas: HTMLCanvasElement; readonly guidance?: typeof headingGuidance }) {
    this.#guidance = options.guidance ?? headingGuidance;
    this.#view = options.view;
    this.#canvas = options.canvas;
    this.#view.addEventListener("resize", this.#handleResize);
  }

  update(snapshot: EditionSnapshot, extraTargets: readonly HeadingTapeTargetInput[] = []): void {
    this.#snapshot = snapshot;
    this.#extraTargets = extraTargets;
    const guidance = this.#guidance(snapshot);
    this.#canvas.setAttribute("aria-label", `航向 ${Math.round(snapshot.flight.headingDeg)}°；${guidance.text}`);
    if (guidance.target?.id !== this.#targetId || guidance.window) this.#displayGuidance = guidance.ratio;
    this.#targetId = guidance.target?.id ?? "";
    const observedAtMs = sampledAtPerformanceTime(
      snapshot.sampledAtMs,
      Date.now(),
      this.#view.performance.now(),
    );
    this.#headingMotion.observe(snapshot.flight.headingDeg, observedAtMs);
    this.#observeMarkerSamples(snapshot, observedAtMs);
    this.#lastObservationMs = observedAtMs;
    if (!Number.isFinite(this.#displayHeading)) this.#displayHeading = this.#headingMotion.step(observedAtMs);
    this.#render();
    if (!this.#frame) {
      this.#lastFrameMs = this.#view.performance.now();
      this.#frame = this.#view.requestAnimationFrame(this.#animate);
    }
  }

  close(): void {
    if (this.#frame) this.#view.cancelAnimationFrame(this.#frame);
    this.#frame = 0;
    this.#view.removeEventListener("resize", this.#handleResize);
  }

  readonly #animate = (nowMs: number): void => {
    const snapshot = this.#snapshot;
    if (!snapshot) { this.#frame = 0; return; }
    const elapsed = Math.min(50, Math.max(0, nowMs - this.#lastFrameMs));
    this.#lastFrameMs = nowMs;
    this.#displayHeading = normalizeHeading(this.#headingMotion.step(nowMs));
    const guidance = this.#guidance(snapshot);
    const target = guidance.target;
    const displayedTargetRelative = target
      ? this.#markerDisplay.get(target.id)?.step(nowMs) ?? target.relativeDeg
      : 0;
    const targetGuidance = guidance.window ? guidance.ratio : target
      ? projectHeadingGuidanceRatio(snapshot.strike?.status === "ready"
        ? snapshot.strike.targetRelativeDeg ?? displayedTargetRelative : displayedTargetRelative, guidance.toleranceDeg) : 0;
    this.#displayGuidance = guidance.window ? targetGuidance
      : this.#displayGuidance + (targetGuidance - this.#displayGuidance) * (1 - Math.exp(-elapsed / 70));
    this.#render();
    if (nowMs - this.#lastObservationMs < 360 || Math.abs(targetGuidance - this.#displayGuidance) > 0.002) {
      this.#frame = this.#view.requestAnimationFrame(this.#animate);
    } else {
      this.#frame = 0;
    }
  };

  readonly #handleResize = (): void => { this.#render(); };

  #observeMarkerSamples(snapshot: EditionSnapshot, observedAtMs: number): void {
    const target = this.#guidance(snapshot).target;
    const inputs = [...(snapshot.navigation?.items ?? [])].map((item) => ({ id: item.id, relativeDeg: item.relativeDeg }));
    inputs.push(...this.#extraTargets);
    if (target && !inputs.some((item) => item.id === target.id)) inputs.push({ id: target.id, relativeDeg: target.relativeDeg });
    const active = new Set(inputs.map((item) => item.id));
    for (const id of this.#markerDisplay.keys()) if (!active.has(id)) this.#markerDisplay.delete(id);
    for (const input of inputs) {
      let motion = this.#markerDisplay.get(input.id);
      if (!motion) {
        motion = new SampledAngleMotion();
        this.#markerDisplay.set(input.id, motion);
      }
      motion.observe(input.relativeDeg, observedAtMs);
    }
  }

  #render(): void {
    const snapshot = this.#snapshot;
    if (!snapshot) return;
    const bounds = this.#canvas.getBoundingClientRect();
    const width = Math.max(320, bounds.width);
    const height = Math.max(72, bounds.height);
    const pixelRatio = this.#view.devicePixelRatio || 1;
    const bitmapWidth = Math.round(width * pixelRatio);
    const bitmapHeight = Math.round(height * pixelRatio);
    if (this.#canvas.width !== bitmapWidth || this.#canvas.height !== bitmapHeight) {
      this.#canvas.width = bitmapWidth;
      this.#canvas.height = bitmapHeight;
    }
    const context = this.#canvas.getContext("2d");
    if (!context) return;
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    context.clearRect(0, 0, width, height);
    const layout = pictureInPictureHeadingLayout(width, height);
    const target = this.#guidance(snapshot).target;
    const pixelsPerDegree = 8 * layout.visualScale * headingTapeScale(target?.distanceKm ?? 20);
    const centerX = width / 2;
    drawTicks(context, this.#displayHeading, centerX, width, pixelsPerDegree, layout);
    drawCenterLine(context, centerX, layout);
    const markerTargets: HeadingTapeTargetInput[] = (snapshot.navigation?.items ?? []).map((item) => ({
      id: item.id,
      kind: item.kind,
      label: item.label,
      relativeDeg: item.relativeDeg,
      distanceKm: item.distanceKm,
      isTarget: item.id === target?.id,
      friendly: item.friendly,
      hostile: item.hostile,
    }));
    markerTargets.push(...this.#extraTargets);
    if (target && !markerTargets.some((item) => item.id === target.id)) {
      markerTargets.push({
        id: target.id,
        kind: target.kind === "airfield_module" ? "airfield" : target.kind,
        label: target.label,
        relativeDeg: target.relativeDeg,
        distanceKm: target.distanceKm,
        isTarget: true,
        friendly: target.kind === "airfield_module" ? false : undefined,
        hostile: target.kind === "airfield_module" ? true : undefined,
      });
    }
    const markers = headingTapeTargetMarkers(markerTargets);
    const renderAtMs = this.#view.performance.now();
    for (const marker of markers) {
      const rawX = centerX + (this.#markerDisplay.get(marker.id)?.step(renderAtMs) ?? marker.relativeDeg) * pixelsPerDegree;
      const edge = 12 * layout.visualScale;
      const inView = rawX >= edge && rawX <= width - edge;
      if (!inView && !marker.isTarget && marker.kind !== "airfield") continue;
      drawMarker(context, marker, clamp(rawX, edge, width - edge), layout, !inView, width);
    }
    drawGuidance(context, this.#guidance(snapshot), this.#displayGuidance, width, layout);
  }
}

function drawTicks(
  context: CanvasRenderingContext2D,
  heading: number,
  centerX: number,
  width: number,
  pixelsPerDegree: number,
  layout: PictureInPictureHeadingLayout,
): void {
  const visibleDegrees = width / pixelsPerDegree;
  const start = Math.floor(heading - visibleDegrees / 2) - 2;
  const end = Math.ceil(heading + visibleDegrees / 2) + 2;
  context.strokeStyle = "rgba(214,233,246,.58)";
  context.fillStyle = "rgba(214,233,246,.78)";
  context.textAlign = "center";
  context.textBaseline = "alphabetic";
  context.font = `${layout.degreeFontPx}px "Microsoft YaHei"`;
  for (let degree = start; degree <= end; degree += 1) {
    const displayed = ((degree % 360) + 360) % 360;
    const x = centerX + (degree - heading) * pixelsPerDegree;
    const major = displayed % 10 === 0;
    const middle = displayed % 5 === 0;
    if (!major && !middle) continue;
    const tickHeight = (major ? 15 : 9) * layout.visualScale;
    context.lineWidth = major ? Math.max(1, 1.5 * layout.visualScale) : 1;
    context.beginPath();
    context.moveTo(x, layout.tickTop);
    context.lineTo(x, layout.tickTop + tickHeight);
    context.stroke();
    if (major && Math.abs(x - centerX) > 30 * layout.visualScale) {
      context.fillText(displayed.toString().padStart(3, "0"), x, layout.degreeTextY);
    }
  }
}

function drawMarker(
  context: CanvasRenderingContext2D,
  marker: HeadingTapeTargetMarker,
  x: number,
  layout: PictureInPictureHeadingLayout,
  overflow: boolean,
  width: number,
): void {
  const scale = layout.visualScale;
  const y = layout.markerY;
  const size = (marker.isTarget ? 7 : 5) * scale;
  const color = marker.kind === "airfield"
    ? marker.friendly ? "#70a7ff" : marker.hostile ? "#ff5a64" : "#d1a267"
    : marker.kind === "zone" ? "#ff5a64" : marker.kind === "poi" ? "#f1bd4e" : "#e8bf58";
  context.save();
  context.globalAlpha = marker.isTarget ? 1 : .72;
  context.strokeStyle = color;
  context.fillStyle = color;
  context.lineWidth = marker.isTarget ? 2 * scale : Math.max(1, scale);
  context.beginPath();
  if (overflow) {
    const direction = Math.sign(marker.relativeDeg) || 1;
    context.moveTo(x + direction * 5 * scale, y);
    context.lineTo(x - direction * 4 * scale, y - 6 * scale);
    context.lineTo(x - direction * 4 * scale, y + 6 * scale);
    context.closePath();
    context.fill();
  } else if (marker.kind === "poi" && marker.overlapsZone) {
    context.strokeStyle = "#ff5a64"; context.fillStyle = "#ff5a64";
    context.arc(x, y, size * .72, 0, Math.PI * 2); context.stroke();
    context.beginPath(); context.arc(x, y, size * .28, 0, Math.PI * 2); context.fill();
    context.strokeStyle = "#ffd34e";
    const outer = size * 1.35; const arm = size * .58;
    for (const [sx, sy] of [[-1, -1], [1, -1], [-1, 1], [1, 1]] as const) {
      context.beginPath(); context.moveTo(x + sx * outer, y + sy * arm); context.lineTo(x + sx * outer, y + sy * outer); context.lineTo(x + sx * arm, y + sy * outer); context.stroke();
    }
  } else if (marker.kind === "zone") {
    if (marker.isTarget) {
      context.strokeStyle = "#ffd34e"; context.lineWidth = 2.4 * scale;
      context.arc(x, y, size + 3 * scale, 0, Math.PI * 2); context.stroke();
      context.beginPath(); context.strokeStyle = color; context.fillStyle = color;
    }
    context.arc(x, y, size, 0, Math.PI * 2); context.stroke();
    context.beginPath(); context.arc(x, y, size * .42, 0, Math.PI * 2); context.fill();
  } else if (headingTargetSymbol(marker.kind) === "aircraft") {
    drawAircraftSymbol(context, x, y, size);
  } else {
    context.moveTo(x, y - size); context.lineTo(x + size, y); context.lineTo(x, y + size); context.lineTo(x - size, y); context.closePath(); context.fill();
  }
  context.font = `700 ${Math.max(8, 7 * scale)}px "Microsoft YaHei"`;
  context.textAlign = "center";
  const label = `${marker.markerLabel} ${marker.distanceKm.toFixed(1)}`;
  const halfLabel = context.measureText(label).width / 2 + 3;
  context.fillText(label, clamp(x, halfLabel, width - halfLabel), layout.distanceY);
  context.restore();
}

function drawAircraftSymbol(context: CanvasRenderingContext2D, x: number, y: number, size: number): void {
  context.beginPath();
  context.moveTo(x, y - size * 1.25);
  context.lineTo(x + size * .28, y - size * .12);
  context.lineTo(x + size, y + size * .35);
  context.lineTo(x + size * .2, y + size * .28);
  context.lineTo(x, y + size);
  context.lineTo(x - size * .2, y + size * .28);
  context.lineTo(x - size, y + size * .35);
  context.lineTo(x - size * .28, y - size * .12);
  context.closePath();
  context.fill();
}

function drawCenterLine(context: CanvasRenderingContext2D, centerX: number, layout: PictureInPictureHeadingLayout): void {
  context.save();
  context.setLineDash([3 * layout.visualScale, 2 * layout.visualScale]);
  context.strokeStyle = "#6de0a3";
  context.lineWidth = 2 * layout.visualScale;
  context.beginPath(); context.moveTo(centerX, 0); context.lineTo(centerX, layout.guidanceTop); context.stroke();
  context.restore();
}

function drawGuidance(
  context: CanvasRenderingContext2D,
  guidance: ReturnType<typeof headingGuidance>,
  guidanceRatio: number,
  width: number,
  layout: PictureInPictureHeadingLayout,
): void {
  const target = guidance.target;
  const centerX = width / 2;
  const trackLeft = width * .075;
  const trackRight = width * .925;
  const halfTrack = (trackRight - trackLeft) / 2;
  const halfHeight = 4 * layout.visualScale;
  context.strokeStyle = "rgba(142,196,225,.38)";
  context.lineWidth = 1;
  context.beginPath(); context.moveTo(0, layout.guidanceTop); context.lineTo(width, layout.guidanceTop); context.stroke();
  context.beginPath(); context.moveTo(trackLeft, layout.guidanceTrackY); context.lineTo(trackRight, layout.guidanceTrackY); context.stroke();
  context.font = `800 ${Math.max(9, 8 * layout.visualScale)}px "Microsoft YaHei"`;
  context.textAlign = "center";
  context.textBaseline = "top";
  context.fillStyle = target ? guidance.color : "rgba(214,233,246,.55)";
  context.fillText(guidance.text, centerX, layout.guidanceTextY);
  for (const fraction of [.3, .6, 1]) {
    const ratio = fraction ** .62;
    for (const sign of [-1, 1]) {
      const x = centerX + sign * ratio * halfTrack;
      context.beginPath();
      context.moveTo(x, layout.guidanceTrackY - halfHeight * .65);
      context.lineTo(x, layout.guidanceTrackY + halfHeight * .65);
      context.stroke();
    }
  }
  const tolerance = guidance.toleranceDeg;
  const approach = guidance.windowMode === "approach" || guidance.windowMode === "correction";
  // A minimum 12 CSS-pixel correction marker stays legible at long range.
  // Never widen an actual impact window: that would imply a false release cue.
  const gateHalf = approach ? Math.max(6, 6 * layout.visualScale, guidance.bandHalfRatio * halfTrack)
    : guidance.bandHalfRatio * halfTrack;
  context.strokeStyle = approach ? "#8ec4e1" : gateHalf > 0 ? "#6de0a3" : "rgba(142,196,225,.38)";
  if (gateHalf > 0) {
    context.fillStyle = approach ? "rgba(142,196,225,.16)" : "rgba(109,224,163,.22)";
    context.fillRect(centerX - gateHalf, layout.guidanceTrackY - halfHeight, gateHalf * 2, halfHeight * 2);
  }
  context.lineWidth = 2 * layout.visualScale;
  context.beginPath();
  context.moveTo(centerX - gateHalf, layout.guidanceTrackY - halfHeight);
  context.lineTo(centerX - gateHalf, layout.guidanceTrackY + halfHeight);
  context.lineTo(centerX + gateHalf, layout.guidanceTrackY + halfHeight);
  context.lineTo(centerX + gateHalf, layout.guidanceTrackY - halfHeight);
  context.stroke();
  context.beginPath();
  context.moveTo(centerX, layout.guidanceTrackY - halfHeight - 2 * layout.visualScale);
  context.lineTo(centerX, layout.guidanceTrackY + halfHeight + 2 * layout.visualScale);
  context.stroke();
  if (target) {
    const x = centerX + guidanceRatio * halfTrack;
    context.fillStyle = guidance.color;
    context.strokeStyle = "#071923";
    context.lineWidth = Math.max(1, layout.visualScale);
    context.beginPath(); context.moveTo(x, layout.guidanceTrackY - 5 * layout.visualScale); context.lineTo(x + 5 * layout.visualScale, layout.guidanceTrackY); context.lineTo(x, layout.guidanceTrackY + 5 * layout.visualScale); context.lineTo(x - 5 * layout.visualScale, layout.guidanceTrackY); context.closePath(); context.fill(); context.stroke();
    if (Math.abs(guidance.relativeDeg) > tolerance) {
      const direction = Math.sign(guidance.relativeDeg) || 1;
      const edgeX = direction < 0 ? trackLeft : trackRight;
      context.beginPath();
      context.moveTo(edgeX, layout.guidanceTrackY);
      context.lineTo(edgeX - direction * 7 * layout.visualScale, layout.guidanceTrackY - 5 * layout.visualScale);
      context.lineTo(edgeX - direction * 7 * layout.visualScale, layout.guidanceTrackY + 5 * layout.visualScale);
      context.closePath();
      context.fill();
    }
  }
}

function normalizeHeading(value: number): number { return (value % 360 + 360) % 360; }
function clamp(value: number, minimum: number, maximum: number): number { return Math.min(maximum, Math.max(minimum, value)); }
