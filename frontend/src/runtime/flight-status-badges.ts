import type { EditionSnapshot } from "./runtime-types";

export type InstrumentBadgeTone = "safe" | "neutral" | "info" | "warning" | "danger";

export interface InstrumentBadgePresentation {
  readonly text: string;
  readonly tone: InstrumentBadgeTone;
  readonly progressPercent: number;
  readonly visible: boolean;
}

export interface FlightStatusPresentation {
  readonly flight: InstrumentBadgePresentation;
  readonly gear: InstrumentBadgePresentation;
}

const HIDDEN_BADGE: InstrumentBadgePresentation = Object.freeze({
  text: "",
  tone: "neutral",
  progressPercent: 0,
  visible: false,
});

export class FlightStatusPresenter {
  #lastGearPercent: number | null = null;
  #gearRetracting = false;

  update(snapshot: EditionSnapshot): FlightStatusPresentation {
    const gearPercent = clamp(snapshot.flight.gearPercent, 0, 100);
    if (this.#lastGearPercent !== null) {
      const delta = gearPercent - this.#lastGearPercent;
      if (Math.abs(delta) >= 0.5) this.#gearRetracting = delta < 0;
    }
    this.#lastGearPercent = gearPercent;
    return Object.freeze({
      flight: flightBadge(snapshot),
      gear: gearBadge(snapshot, gearPercent, this.#gearRetracting),
    });
  }
}

export class FlightStatusBadgeRenderer {
  readonly #flight: HTMLElement;
  readonly #gear: HTMLElement;

  constructor(elements: { readonly flight: HTMLElement; readonly gear: HTMLElement }) {
    this.#flight = elements.flight;
    this.#gear = elements.gear;
  }

  update(presentation: FlightStatusPresentation): void {
    applyBadge(this.#flight, presentation.flight);
    applyBadge(this.#gear, presentation.gear);
  }
}

function flightBadge(snapshot: EditionSnapshot): InstrumentBadgePresentation {
  if (!snapshot.connected) return HIDDEN_BADGE;
  const [text, tone] = ({
    idle: ["待机", "neutral"],
    hangar: ["机库", "neutral"],
    arming: ["部署", "info"],
    alive: snapshot.flight.onGround ? ["地面", "neutral"] : ["飞行", "safe"],
    "loss-pending": ["状态切换", "warning"],
    "wait-next": ["待复活", "warning"],
  } as const)[snapshot.phase] as readonly [string, InstrumentBadgeTone];
  return Object.freeze({ text, tone, progressPercent: 100, visible: true });
}

function gearBadge(
  snapshot: EditionSnapshot,
  gearPercent: number,
  retracting: boolean,
): InstrumentBadgePresentation {
  if (!snapshot.connected) return HIDDEN_BADGE;
  const landing = snapshot.landing;
  if (landing?.settings.enabled) {
    if (landing.gearPercent === null) return HIDDEN_BADGE;
    if (landing.gearRisk === "over-limit") return { text: "起落架超参考限速", tone: "danger", progressPercent: 100, visible: true };
    if (landing.gearRisk === "extension-too-fast") return { text: "放轮前减速", tone: "warning", progressPercent: 100, visible: true };
    if (landing.gearRisk === "near-limit") return { text: "接近起落架限速", tone: "warning", progressPercent: 100, visible: true };
    if (landing.gearPercent <= .5) return HIDDEN_BADGE;
    return { text: `${retracting ? "收轮" : "放轮"} ${Math.round(landing.gearPercent)}%`, tone: "info", progressPercent: landing.gearPercent, visible: true };
  }
  const moving = gearPercent > 0.5 && gearPercent < 99.5;
  if (moving) {
    return Object.freeze({
      text: `${retracting ? "收轮" : "放轮"} ${Math.round(gearPercent)}%`,
      tone: retracting ? "info" : "warning",
      progressPercent: retracting ? 100 - gearPercent : gearPercent,
      visible: true,
    });
  }
  const airborne = snapshot.flight.iasKmh > 80 || snapshot.flight.altitudeM > 50;
  if (snapshot.phase === "alive" && airborne && gearPercent > 50) {
    return Object.freeze({ text: "起落架未收", tone: "danger", progressPercent: 100, visible: true });
  }
  return HIDDEN_BADGE;
}

function applyBadge(element: HTMLElement, presentation: InstrumentBadgePresentation): void {
  element.hidden = !presentation.visible;
  element.textContent = presentation.text;
  element.classList.remove("tone-safe", "tone-neutral", "tone-info", "tone-warning", "tone-danger");
  element.classList.add(`tone-${presentation.tone}`);
  element.style.setProperty("--badge-progress", `${clamp(presentation.progressPercent, 0, 100)}%`);
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, Number.isFinite(value) ? value : 0));
}
