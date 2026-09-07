import type { EditionSnapshot, NavigationItem } from "./runtime-types";
import { discoverBridgeEndpoint, fetchBridgeResource } from "./bridge-discovery";
import { normalizeOfficialMapInfo } from "./map-info";
import { headingRayToMapEdge } from "./map-heading-ray";

/** Official map objects only. Both the page and its PiP window use this renderer. */
export class PublicNavigationMap {
  #snapshot: EditionSnapshot | null = null;
  readonly #canvas: HTMLCanvasElement;
  readonly #select: (id: string) => void;
  readonly #basemap: PublicNavigationMap | undefined;
  #mapInfo: Readonly<Record<string, unknown>> | null = null;
  #identity = "";
  #image: ImageBitmap | null = null;
  #loading: AbortController | null = null;
  #lastFetchMs = 0;
  #rect = { x: 20, y: 20, width: 60, height: 60 };
  constructor(canvas: HTMLCanvasElement, select: (id: string) => void, basemap?: PublicNavigationMap) {
    this.#canvas = canvas;
    this.#select = select;
    this.#basemap = basemap;
    canvas.addEventListener("click", this.#click);
    canvas.ownerDocument.defaultView?.addEventListener("resize", this.#resize);
  }
  update(snapshot: EditionSnapshot, mapInfo: Readonly<Record<string, unknown>> | null = null): void {
    this.#snapshot = snapshot;
    this.#mapInfo = mapInfo;
    if (!this.#basemap) this.#updateImage(snapshot, mapInfo);
    const canvas = this.#canvas;
    const canvasRect = canvas.getBoundingClientRect();
    const ratio = canvas.ownerDocument.defaultView?.devicePixelRatio ?? 1;
    const width = Math.max(100, canvasRect.width), height = Math.max(100, canvasRect.height);
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.fillStyle = "#0b202e"; ctx.fillRect(0, 0, width, height);
    const aspect = (this.#basemap ?? this).aspectRatio;
    const pairedPhone = canvas.ownerDocument.body.dataset.mobilePaired === "true";
    const mapWidth = pairedPhone ? Math.max(width, height * aspect) : Math.min(width - 16, (height - 16) * aspect), mapHeight = mapWidth / aspect;
    const rect = this.#rect = { x: (width - mapWidth) / 2, y: (height - mapHeight) / 2, width: mapWidth, height: mapHeight };
    (this.#basemap ?? this).paintBasemap(ctx, rect);
    const xy = (p: { x: number; y: number }) => [rect.x + p.x * rect.width, rect.y + p.y * rect.height] as const;
    const nav = snapshot.navigation;
    if (!nav) return;
    const player = nav.player ? xy(nav.player) : null;
    if (nav.player && player) {
      const ray = headingRayToMapEdge(nav.player.x, nav.player.y, snapshot.flight.headingDeg);
      if (ray) {
        ctx.strokeStyle = "#799ca3"; ctx.lineWidth = 1; ctx.setLineDash([6, 6]);
        ctx.beginPath(); ctx.moveTo(...player); ctx.lineTo(...xy({ x: ray.end[0], y: ray.end[1] })); ctx.stroke(); ctx.setLineDash([]);
      }
    }
    if (player && nav.target) {
      const target = xy(nav.target);
      ctx.strokeStyle = "#ffd87b"; ctx.setLineDash([4, 5]); ctx.beginPath(); ctx.moveTo(...player); ctx.lineTo(...target); ctx.stroke(); ctx.setLineDash([]);
    }
    for (const item of nav.items) {
      const [x, y] = xy(item);
      ctx.strokeStyle = item.selected ? "#ffda7a" : item.friendly ? "#85ccff" : "#ff9397";
      ctx.fillStyle = ctx.strokeStyle; ctx.lineWidth = item.selected ? 3 : 1.5;
      ctx.beginPath();
      if (item.kind === "zone") ctx.arc(x, y, 7, 0, Math.PI * 2);
      else if (item.runwayStart && item.runwayEnd) {
        ctx.moveTo(...xy({ x: item.runwayStart[0], y: item.runwayStart[1] }));
        ctx.lineTo(...xy({ x: item.runwayEnd[0], y: item.runwayEnd[1] }));
      } else ctx.rect(x - 7, y - 4, 14, 8);
      ctx.stroke(); ctx.font = '10px "Microsoft YaHei"';
      ctx.fillText(item.label, Math.min(width - 65, Math.max(3, x + 9)), Math.max(12, y));
    }
    if (player) {
      ctx.save(); ctx.translate(...player); ctx.rotate(snapshot.flight.headingDeg * Math.PI / 180);
      ctx.fillStyle = "#ffda7a"; ctx.beginPath(); ctx.moveTo(0, -9); ctx.lineTo(6, 7); ctx.lineTo(0, 3); ctx.lineTo(-6, 7); ctx.closePath(); ctx.fill(); ctx.restore();
    }
  }
  get aspectRatio(): number {
    const scale = this.#snapshot?.navigation?.mapScaleM;
    return scale && scale[0] > 0 && scale[1] > 0 ? scale[0] / scale[1] : this.#image ? this.#image.width / this.#image.height : 1;
  }
  paintBasemap(context: CanvasRenderingContext2D, rect: { x: number; y: number; width: number; height: number }): void {
    if (!this.#image) return;
    context.save(); context.globalAlpha = .6; context.drawImage(this.#image, rect.x, rect.y, rect.width, rect.height); context.restore();
  }
  close(): void {
    this.#snapshot = null; this.#loading?.abort(); this.#loading = null; this.#image?.close(); this.#image = null;
    this.#canvas.removeEventListener("click", this.#click); this.#canvas.ownerDocument.defaultView?.removeEventListener("resize", this.#resize);
  }
  #updateImage(snapshot: EditionSnapshot, mapInfo: Readonly<Record<string, unknown>> | null): void {
    const bounds = normalizeOfficialMapInfo(mapInfo);
    const identity = snapshot.connected && bounds && snapshot.navigation?.player ? JSON.stringify(bounds) : "";
    if (identity !== this.#identity) {
      this.#identity = identity; this.#loading?.abort(); this.#loading = null; this.#image?.close(); this.#image = null; this.#lastFetchMs = 0;
    }
    const now = Date.now();
    if (!identity || this.#loading || now - this.#lastFetchMs < (this.#image ? 30_000 : 3_000)) return;
    this.#lastFetchMs = now;
    const controller = this.#loading = new AbortController();
    void this.#refreshImage(controller);
  }
  async #refreshImage(controller: AbortController): Promise<void> {
    try {
      const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(3_000)]);
      const endpoint = await discoverBridgeEndpoint(fetch, "", signal);
      const response = await fetchBridgeResource(fetch, new URL("api/v1/8111/map-image", endpoint), {
        method: "GET", mode: "cors", cache: "no-store", credentials: "omit", redirect: "error", signal,
      });
      if (!response.ok) return;
      const blob = await response.blob();
      if (!blob.type.startsWith("image/") || blob.size === 0 || blob.size > 8 * 1024 * 1024) return;
      const next = await createImageBitmap(blob);
      if (controller.signal.aborted || this.#loading !== controller) { next.close(); return; }
      this.#image?.close(); this.#image = next; this.#resize();
    } catch {
      // Official markers remain usable while the game's image is unavailable.
    } finally { if (this.#loading === controller) this.#loading = null; }
  }
  readonly #resize = (): void => { if (this.#snapshot) this.update(this.#snapshot, this.#mapInfo); };
  readonly #click = (event: MouseEvent): void => {
    const rect = this.#canvas.getBoundingClientRect();
    let selected: NavigationItem | null = null, best = 22;
    for (const item of this.#snapshot?.navigation?.items ?? []) {
      const distance = Math.hypot(event.clientX - rect.left - this.#rect.x - item.x * this.#rect.width, event.clientY - rect.top - this.#rect.y - item.y * this.#rect.height);
      if (distance < best) { selected = item; best = distance; }
    }
    if (selected) this.#select(selected.id);
  };
}
