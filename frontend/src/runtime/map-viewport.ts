export interface MapViewportRect { readonly x: number; readonly y: number; readonly width: number; readonly height: number }

/** One CSS-pixel transform for rendering, zoom anchors and map hit testing. */
export class MapViewport {
  #zoom = 1;
  #center = { x: .5, y: .5 };
  readonly #canvas: HTMLCanvasElement;
  readonly #fitRect: () => MapViewportRect;
  readonly #redraw: () => void;
  readonly #events = new AbortController();
  readonly #controls: HTMLDivElement;

  constructor(canvas: HTMLCanvasElement, fitRect: () => MapViewportRect, redraw: () => void,
    select: (event: PointerEvent, pressDurationMs: number) => void) {
    this.#canvas = canvas; this.#fitRect = fitRect; this.#redraw = redraw;
    const signal = this.#events.signal;
    canvas.tabIndex = 0;
    canvas.style.touchAction = "none";
    canvas.title = "滚轮 / 双指缩放，拖动平移，双击或按 0 显示全图";
    const controls = this.#controls = canvas.ownerDocument.createElement("div");
    controls.className = "map-controls";
    controls.setAttribute("role", "group"); controls.setAttribute("aria-label", "地图缩放");
    for (const [text, label, action] of [
      ["+", "放大地图", () => this.zoomBy(1.5)], ["−", "缩小地图", () => this.zoomBy(1 / 1.5)],
      ["全图", "适配全图", () => this.reset()],
    ] as const) {
      const button = canvas.ownerDocument.createElement("button");
      button.type = "button"; button.textContent = text; button.setAttribute("aria-label", label);
      button.addEventListener("click", action, { signal }); controls.append(button);
    }
    canvas.after(controls);
    canvas.addEventListener("wheel", event => {
      event.preventDefault();
      const bounds = canvas.getBoundingClientRect();
      const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? bounds.height : 1);
      this.zoomBy(Math.exp(-Math.max(-500, Math.min(500, delta)) * .002), event.clientX - bounds.left, event.clientY - bounds.top);
    }, { passive: false, signal });
    canvas.addEventListener("dblclick", event => { if (!event.altKey) this.reset(); }, { signal });
    canvas.addEventListener("keydown", event => {
      if (["+", "=", "-", "0", "Home"].includes(event.key)) {
        event.preventDefault();
        if (event.key === "0" || event.key === "Home") this.reset();
        else this.zoomBy(event.key === "-" ? 1 / 1.5 : 1.5);
      }
    }, { signal });
    const pointers = new Map<number, { x: number; y: number }>();
    let start: { id: number; x: number; y: number; at: number } | null = null;
    let dragged = false;
    const gesture = () => {
      const [a, b] = [...pointers.values()];
      return !a ? null : !b ? { ...a, distance: 0 }
        : { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, distance: Math.hypot(a.x - b.x, a.y - b.y) };
    };
    canvas.addEventListener("pointerdown", event => {
      if (event.button !== 0) return;
      if (pointers.size === 0) { start = { id: event.pointerId, x: event.clientX, y: event.clientY, at: performance.now() }; dragged = false; }
      else dragged = true;
      pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      canvas.setPointerCapture(event.pointerId);
    }, { signal });
    canvas.addEventListener("pointermove", event => {
      if (!pointers.has(event.pointerId)) return;
      const before = gesture()!;
      pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      const after = gesture()!;
      if (start && Math.hypot(event.clientX - start.x, event.clientY - start.y) > 8) dragged = true;
      if (!dragged) return;
      const bounds = canvas.getBoundingClientRect();
      if (before.distance > 0 && after.distance > 0) this.zoomBy(after.distance / before.distance, before.x - bounds.left, before.y - bounds.top);
      this.#pan(after.x - before.x, after.y - before.y);
    }, { signal });
    const finish = (event: PointerEvent) => {
      if (!pointers.delete(event.pointerId)) return;
      if (event.type === "pointerup" && !dragged && start?.id === event.pointerId
        && Math.hypot(event.clientX - start.x, event.clientY - start.y) <= 8) select(event, performance.now() - start.at);
      if (event.type !== "pointerup") dragged = true;
      if (pointers.size === 0) start = null;
    };
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"] as const) canvas.addEventListener(type, finish, { signal });
  }

  rect(): MapViewportRect {
    const fit = this.#fitRect(), bounds = this.#canvas.getBoundingClientRect();
    const width = fit.width * this.#zoom, height = fit.height * this.#zoom;
    const axis = (offset: number, base: number, size: number, center: number, available: number) => size >= available
      ? Math.max(available - size, Math.min(0, offset + base / 2 - center * size))
      : Math.max(0, Math.min(available - size, offset + (base - size) / 2));
    return { x: axis(fit.x, fit.width, width, this.#center.x, bounds.width),
      y: axis(fit.y, fit.height, height, this.#center.y, bounds.height), width, height };
  }

  reset(redraw = true): void { this.#zoom = 1; this.#center = { x: .5, y: .5 }; if (redraw) this.#redraw(); }

  zoomBy(factor: number, x?: number, y?: number): void {
    const before = this.rect(), bounds = this.#canvas.getBoundingClientRect();
    if (before.width <= 0 || before.height <= 0) return;
    const anchor = { x: x ?? bounds.width / 2, y: y ?? bounds.height / 2 };
    const point = { x: (anchor.x - before.x) / before.width, y: (anchor.y - before.y) / before.height };
    this.#zoom = Math.max(1, Math.min(16, this.#zoom * factor));
    const fit = this.#fitRect();
    this.#center = { x: point.x + (fit.x + fit.width / 2 - anchor.x) / (fit.width * this.#zoom),
      y: point.y + (fit.y + fit.height / 2 - anchor.y) / (fit.height * this.#zoom) };
    this.#redraw();
  }

  #pan(dx: number, dy: number): void {
    const rect = this.rect(), fit = this.#fitRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    this.#center = { x: (fit.x + fit.width / 2 - rect.x - dx) / rect.width,
      y: (fit.y + fit.height / 2 - rect.y - dy) / rect.height };
    this.#redraw();
  }

  close(): void { this.#events.abort(); this.#controls.remove(); }
}
