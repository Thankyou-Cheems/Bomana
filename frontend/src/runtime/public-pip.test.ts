import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PublicFlightInstruments } from "./public-flight-instruments";
import type { FlightStatusPresentation } from "./flight-status-badges";
import { readPipMapVisible, savePipMapVisible } from "./pip-map-preference";
import { PublicPictureInPicture } from "./public-pip";
import { PublicNavigationMap } from "./public-pip-mini-map";
import { setFlightDisplayMode } from "./flight-display-mode";
import type { EditionSnapshot } from "./runtime-types";

// Keep the controller, preference storage and toggle real. Rendering itself is
// covered by pip-window-smoke; these seams hold stylesheet completion pending.
vi.mock("./public-flight-instruments", () => ({
  PublicFlightInstruments: vi.fn(class {
    update = vi.fn();
    close = vi.fn();
    constructor(host: HTMLElement, options: { trailingAction: HTMLElement }) { host.append(options.trailingAction); }
  }),
}));
vi.mock("./public-pip-mini-map", () => ({
  PublicNavigationMap: vi.fn(class { update = vi.fn(); close = vi.fn(); }),
}));

function pipWindow() {
  const attributes = new Map<string, string>();
  const button = Object.assign(new EventTarget(), {
    dataset: {} as Record<string, string>, title: "",
    setAttribute: (name: string, value: string) => attributes.set(name, value),
    getAttribute: (name: string) => attributes.get(name) ?? null,
    click(this: EventTarget) { this.dispatchEvent(new Event("click")); },
  });
  const classes = new Set<string>();
  const cockpit = { classList: { toggle: (name: string, enabled: boolean) => enabled ? classes.add(name) : classes.delete(name) } };
  const map = { hidden: false };
  const canvas = {};
  const stylesheet = { onload: null as (() => void) | null, onerror: null as (() => void) | null };
  const nodes = new Map<string, unknown>();
  const host = { append: (action: HTMLElement) => nodes.set("#pip-map-toggle", action) };
  const document = {
    head: { append() {} }, documentElement: { lang: "" },
    body: { set innerHTML(_html: string) {
      nodes.set(".pip-cockpit", cockpit); nodes.set(".pip-mini-map", map);
      nodes.set(".pip-mini-map canvas", canvas); nodes.set(".pip-instruments-slot", host);
    } },
    createElement: (tag: string) => tag === "link" ? stylesheet : button,
    querySelector: (selector: string) => nodes.get(selector) ?? null,
  };
  const view = Object.assign(new EventTarget(), {
    document, closed: false, resizeTo: vi.fn(),
    close(this: EventTarget & { closed: boolean }) { this.closed = true; this.dispatchEvent(new Event("pagehide")); },
  });
  return { view, button, classes, map, canvas, stylesheet };
}

const snapshot = { sampledAtMs: 1000 } as EditionSnapshot;
const flightStatus = { flight: { text: "飞行" } } as FlightStatusPresentation;
const basemap = {} as PublicNavigationMap;

function openFixture(initialVisible: boolean, ...windows: ReturnType<typeof pipWindow>[]) {
  const requestWindow = vi.fn();
  for (const { view } of windows) requestWindow.mockResolvedValueOnce(view);
  vi.stubGlobal("window", { isSecureContext: true, documentPictureInPicture: { requestWindow }, setTimeout, clearTimeout });
  savePipMapVisible("Standard", initialVisible);
  const visibility = vi.fn();
  const pip = new PublicPictureInPicture(vi.fn(), vi.fn(), visibility, basemap);
  return { pip, requestWindow, visibility };
}

function expectVisibility(fixture: ReturnType<typeof pipWindow>, visible: boolean) {
  expect(fixture.map.hidden).toBe(!visible);
  expect(fixture.classes.has("has-mini-map")).toBe(visible);
  expect(fixture.button.getAttribute("aria-pressed")).toBe(String(visible));
  expect(fixture.button.getAttribute("aria-expanded")).toBe(String(visible));
  expect(fixture.button.getAttribute("aria-label")).toBe(visible ? "点击收起小地图" : "点击展开小地图");
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
  const values = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
  });
  setFlightDisplayMode("simulator");
});
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("Standard PiP opening with a pending stylesheet", () => {
  it("shares Air Realistic mode, preserves the map choice and unsubscribes after closing", async () => {
    setFlightDisplayMode("air-realistic");
    const fixture = pipWindow();
    const { pip, requestWindow } = openFixture(true, fixture);
    const opening = pip.toggle(snapshot, flightStatus);
    await Promise.resolve();
    expect(requestWindow).toHaveBeenCalledWith({ width: 360, height: 360 });
    expectVisibility(fixture, false);
    expect(readPipMapVisible("Standard")).toBe(true);
    fixture.stylesheet.onload!();
    await opening;
    const map = vi.mocked(PublicNavigationMap).mock.instances[0]!;
    expect(map.update).not.toHaveBeenCalled();
    setFlightDisplayMode("simulator");
    expectVisibility(fixture, true);
    expect(map.update).toHaveBeenLastCalledWith(snapshot);
    expect(fixture.view.resizeTo).toHaveBeenLastCalledWith(910, 188);
    setFlightDisplayMode("air-realistic");
    expectVisibility(fixture, false);
    expect(fixture.view.resizeTo).toHaveBeenLastCalledWith(360, 360);
    fixture.view.close();
    fixture.view.resizeTo.mockClear();
    setFlightDisplayMode("simulator");
    expect(fixture.view.resizeTo).not.toHaveBeenCalled();
  });
  it.each([false, true])("applies saved map visibility %s before the stylesheet finishes", async visible => {
    const fixture = pipWindow();
    const { pip, requestWindow, visibility } = openFixture(visible, fixture);
    const opening = pip.toggle(snapshot, flightStatus);
    await Promise.resolve(); // requestWindow settles; stylesheet stays pending.

    expect(requestWindow).toHaveBeenCalledWith({ width: visible ? 910 : 720, height: 188 });
    expectVisibility(fixture, visible);
    expect(visibility).toHaveBeenLastCalledWith(visible);
    expect(PublicNavigationMap).not.toHaveBeenCalled();

    fixture.stylesheet.onload!();
    await opening;
    expectVisibility(fixture, visible);
    expect(PublicNavigationMap).toHaveBeenCalledExactlyOnceWith(fixture.canvas, expect.any(Function), basemap);
    const map = vi.mocked(PublicNavigationMap).mock.instances[0]!;
    if (visible) expect(map.update).toHaveBeenLastCalledWith(snapshot);
    else expect(map.update).not.toHaveBeenCalled();
    fixture.view.close();
  });

  it.each([false, true])("retains a toggle from %s and the latest snapshot during stylesheet loading", async initialVisible => {
    const fixture = pipWindow();
    const { pip, visibility } = openFixture(initialVisible, fixture);
    const opening = pip.toggle(snapshot, flightStatus);
    await Promise.resolve();
    fixture.button.click();
    const visible = !initialVisible;
    expectVisibility(fixture, visible);
    expect(readPipMapVisible("Standard")).toBe(visible);
    expect(visibility).toHaveBeenLastCalledWith(visible);
    const latest = { ...snapshot, sampledAtMs: 2000 };
    const latestStatus = { ...flightStatus };
    pip.update(latest, latestStatus);

    fixture.stylesheet.onload!();
    await opening;
    expectVisibility(fixture, visible);
    expect(vi.mocked(PublicFlightInstruments).mock.instances[0]!.update).toHaveBeenLastCalledWith(latest, latestStatus);
    const map = vi.mocked(PublicNavigationMap).mock.instances[0]!;
    if (visible) expect(map.update).toHaveBeenLastCalledWith(latest);
    else expect(map.update).not.toHaveBeenCalled();
    fixture.view.close();
    expect(map.close).toHaveBeenCalledOnce();
  });

  it("ignores a closed window's late stylesheet after reopening", async () => {
    const old = pipWindow(), current = pipWindow();
    const { pip } = openFixture(false, old, current);
    const firstOpening = pip.toggle(snapshot, flightStatus);
    await Promise.resolve();
    const oldInstruments = vi.mocked(PublicFlightInstruments).mock.instances[0]!;
    await pip.toggle(snapshot, flightStatus); // Close while CSS is still pending.
    expect(old.view.closed).toBe(true);
    expect(oldInstruments.close).toHaveBeenCalledOnce();

    const currentOpening = pip.toggle(snapshot, flightStatus);
    await Promise.resolve();
    expectVisibility(current, false);
    current.button.click();
    current.stylesheet.onload!();
    await currentOpening;
    const map = vi.mocked(PublicNavigationMap).mock.instances[0]!;
    const instruments = vi.mocked(PublicFlightInstruments).mock.instances[1]!;
    vi.mocked(map.update).mockClear();
    vi.mocked(instruments.update).mockClear();

    old.stylesheet.onload!();
    await firstOpening;
    old.view.dispatchEvent(new Event("pagehide"));
    expect(PublicNavigationMap).toHaveBeenCalledExactlyOnceWith(current.canvas, expect.any(Function), basemap);
    expectVisibility(current, true);
    expect(map.update).not.toHaveBeenCalled();
    expect(instruments.update).not.toHaveBeenCalled();
    expect(map.close).not.toHaveBeenCalled();
    expect(instruments.close).not.toHaveBeenCalled();
    current.view.close();
    expect(map.close).toHaveBeenCalledOnce();
    expect(instruments.close).toHaveBeenCalledOnce();
  });
});
