import type { EditionSnapshot } from "./runtime-types";
import type { BasemapPainter } from "./basemap-painter";
import { AirMapAutoRange, airMapAircraftAngle, airMapMarker, airMapOffset, airMapRings, airRealisticSituation } from "./air-realistic-model";
import { flightModeSwitch } from "./flight-mode-switch";
import { speedObservationCurrent, speedStripPresentation } from "./speed-strip-renderer";
import { drawAircraftMapSymbol } from "./aircraft-map-symbol";
import { AIR_CONTACT_TRAIL_MS, AirContactMotionEstimator, airContactClosingLabel, airContactColor } from "./air-contact-motion";
import { AirEnergyTrend } from "./air-energy";
import { drawBombingZoneSymbol } from "./navigation-symbols";
import { AirVelocityVectorEstimator } from "./air-velocity-vector";
import { observeAirVelocityVectorEnabled, setAirVelocityVectorEnabled } from "./air-velocity-preference";

/** Shared Air Realistic map for Standard, Enhanced and native windows. */
export class AirRealisticInstruments {
  readonly root: HTMLElement;
  readonly #canvas: HTMLCanvasElement;
  readonly #context: CanvasRenderingContext2D;
  readonly #resize: ResizeObserver;
  readonly #paintBasemap?: BasemapPainter;
  readonly #view: Window;
  readonly #timer: number;
  readonly #autoRange = new AirMapAutoRange();
  readonly #motion = new AirContactMotionEstimator();
  readonly #energy = new AirEnergyTrend();
  readonly #velocity = new AirVelocityVectorEstimator();
  readonly #stopVelocityPreference: () => void;
  #snapshot: EditionSnapshot | null = null;
  #observedAt = 0;
  #headingUp = true;
  #velocityEnabled = true;

  constructor(host: HTMLElement, paintBasemap?: BasemapPainter) {
    const doc = host.ownerDocument;
    this.#view = doc.defaultView!;
    this.#paintBasemap = paintBasemap;
    this.root = doc.createElement("section");
    this.root.className = "air-realistic-instruments";
    this.root.setAttribute("aria-label", "空历飞行仪表");
    this.root.innerHTML = `<div class="ar-map"><canvas aria-label="自机居中空中态势图" title="机体旁为水平距离 km；最近三架的接近／远离速度标在尾迹旁，单位 m/s，不是目标空速。机头朝向表示已报告方向；淡色尾迹为最近 6 秒位置。近处敌机偏红，远处偏淡，友机为淡蓝。‘同向×N’表示疑似低速同向机群，不判断 AI 或玩家。图标只区分机种，不识别具体机型。只用 8111 水平坐标，不表示高度、锁定或射击提前量；目标消失即清除。E↑/E↓ 为本机比能量升降。"></canvas></div>
      <header class="ar-header">
        <button type="button" class="ar-orientation" title="点击切换航向朝上 / 北向朝上">航向 ↑</button>
        <button type="button" class="ar-velocity-toggle" aria-label="显示速度矢量" aria-pressed="true" title="一键开关速度矢量，记住选择。白色为机头，黄色为水平对地速度方向。">速矢 开</button>
        <span class="ar-scale" title="自动覆盖最近三架已报告敌机；远处目标以边缘箭头提示">自动</span>
        <span class="ar-status" role="status">待连接</span>
      </header>
      <div class="ar-telemetry"><span class="ar-velocity-readout" title="黄色箭头为 8111 连续地图位置估计的水平对地速度方向；白色为机头。箭头长度固定，只表示方向。不是三维空速、导弹方向或规避成功判定。">速度矢量 —</span><div class="ar-config"><span class="ar-flaps" hidden></span><span class="ar-gear" hidden></span><span class="ar-brake" hidden></span></div></div>
      <section class="ar-speed" aria-label="结构限速">
        <div class="ar-speed-values"><strong class="ar-ias">IAS —</strong><span class="ar-energy" hidden></span><span class="ar-speed-state"></span></div>
        <div class="ar-speed-track" aria-hidden="true"><i class="ar-speed-fill"></i>
          <b class="ar-speed-node caution"><span>90% 预警</span></b><b class="ar-speed-node warning"><span>95% 减速</span></b><b class="ar-speed-node critical"><span>100% 限速</span></b>
        </div>
      </section>`;
    host.append(this.root);
    this.root.querySelector(".ar-header")!.prepend(flightModeSwitch(doc, "air-realistic"));
    this.root.querySelector(".ar-orientation")!.addEventListener("click", () => {
      this.#headingUp = !this.#headingUp;
      this.#text(".ar-orientation", this.#headingUp ? "航向 ↑" : "北向 ↑", "点击切换航向朝上 / 北向朝上");
      this.#render();
    });
    this.#canvas = this.root.querySelector("canvas")!;
    this.#context = this.#canvas.getContext("2d")!;
    this.root.querySelector(".ar-velocity-toggle")!.addEventListener("click", () => setAirVelocityVectorEnabled(!this.#velocityEnabled));
    this.#stopVelocityPreference = observeAirVelocityVectorEnabled(enabled => {
      this.#velocityEnabled = enabled;
      const button = this.root.querySelector<HTMLButtonElement>(".ar-velocity-toggle")!;
      button.textContent = enabled ? "速矢 开" : "速矢 关";
      button.setAttribute("aria-pressed", String(enabled));
      this.root.querySelector<HTMLElement>(".ar-velocity-readout")!.hidden = !enabled;
      this.#render();
    });
    this.#resize = new host.ownerDocument.defaultView!.ResizeObserver(() => this.#render());
    this.#resize.observe(this.root);
    // Smooth only view scale; enemy positions always come from the current frame.
    this.#timer = this.#view.setInterval(() => this.#render(), 50);
  }

  update(snapshot: EditionSnapshot): void {
    if (!this.#snapshot || snapshot.sampledAtMs !== this.#snapshot.sampledAtMs) this.#observedAt = this.#view.performance.now();
    this.#snapshot = snapshot;
    this.#render();
  }
  close(): void { this.#resize.disconnect(); this.#view.clearInterval(this.#timer); this.#stopVelocityPreference(); this.#motion.reset(); this.#energy.reset(); this.#velocity.reset(); this.root.remove(); }
  #text(selector: string, text: string, title = text, tone = ""): HTMLElement {
    const element = this.root.querySelector<HTMLElement>(selector)!;
    element.textContent = text; element.title = title; element.dataset.tone = tone;
    return element;
  }
  #render(): void {
    if (!this.root.offsetWidth || !this.#snapshot) return;
    const snapshot = this.#snapshot, at = this.#view.performance.now();
    const elapsed = Math.max(0, at - this.#observedAt);
    const situation = airRealisticSituation(snapshot, 20, snapshot.sampledAtMs + elapsed);
    const velocity = this.#velocity.observe(snapshot, snapshot.sampledAtMs + elapsed);
    const vector = this.#velocityEnabled ? velocity : null;
    const readout = this.root.querySelector<HTMLElement>(".ar-velocity-readout")!;
    const deviation = vector ? Math.round(Math.abs(vector.relativeDeg)) : 0;
    readout.textContent = vector
      ? `航迹 ${String(Math.round(vector.headingDeg) % 360).padStart(3, "0")}° · ${deviation === 0 ? "机头同向" : `偏${vector.relativeDeg < 0 ? "左" : "右"} ${deviation}°`} · 地速 ${Math.round(vector.groundSpeedMps * 3.6)} km/h`
      : "速度矢量 —";
    const motions = this.#motion.observe(snapshot, situation.contacts, situation.contactsCurrent);
    const rangeKm = this.#autoRange.update(situation.contacts.map(contact => contact.distanceKm), situation.contactsCurrent, at);
    const live = elapsed <= 1500 && speedObservationCurrent(snapshot, snapshot.sampledAtMs + elapsed);
    this.root.dataset.stale = String(!situation.available || situation.delayed);
    this.#text(".ar-scale", `±${rangeKm.toFixed(1)} km`, "自动范围：短边半幅；覆盖最近三架已报告敌机，远处目标显示边缘箭头。缩小延迟 3 秒。");
    const status = this.#text(".ar-status", !situation.available ? "未定位" : !situation.contactsCurrent ? "延迟" : "",
      `${snapshot.flight.aircraft || "机型待识别"} · ${situation.reason || (situation.contactsCurrent ? "当前已报告敌机；无报告不代表空域安全" : "地图延迟，敌机已隐藏")} · 平面距离`, situation.contactsCurrent ? "" : "warning");
    status.hidden = situation.contactsCurrent;
    const speed = speedStripPresentation(snapshot, snapshot.sampledAtMs + elapsed);
    const speedRoot = this.root.querySelector<HTMLElement>(".ar-speed")!;
    speedRoot.dataset.level = speed.levelClass; speedRoot.title = speed.detail;
    this.root.querySelector<HTMLElement>(".ar-speed-values")!.dataset.level = speed.levelClass;
    this.#text(".ar-ias", live ? `IAS ${Math.round(snapshot.flight.iasKmh)}` : "IAS —", speed.detail);
    const energy = this.#energy.observe(snapshot, snapshot.sampledAtMs + elapsed);
    const energyElement = this.#text(".ar-energy", energy === "up" ? "E↑" : energy === "down" ? "E↓" : "",
      "比能量由真空速和高度合成。E↑ 升高，E↓ 下降；把速度换成高度时可能不变。只在变化明显且 TAS 有效时显示，不是爬升率，也不表示敌情。", energy ?? "");
    energyElement.hidden = !energy; energyElement.dataset.energy = energy ?? "none";
    this.#text(".ar-speed-state", speed.limitsKnown ? speed.levelClass === "safe" ? "" : speed.stateText : live ? "限速未知" : "", speed.detail);
    const track = this.root.querySelector<HTMLElement>(".ar-speed-track")!;
    track.hidden = !speed.limitsKnown;
    this.root.querySelectorAll<HTMLElement>(".ar-speed-node").forEach((node, index) => {
      node.style.left = `${speed.markerPercents[index]}%`;
      track.style.setProperty(["--speed-caution", "--speed-warning", "--speed-limit"][index]!, `${speed.markerPercents[index]}%`);
    });
    this.root.querySelector<HTMLElement>(".ar-speed-fill")!.style.width = `${speed.fillPercent}%`;
    const landing = live ? snapshot.landing : null;
    for (const [selector, name, value, limit, risk] of [
      [".ar-flaps", "襟翼", landing?.flapsPercent, landing?.flapReference?.limitIasKmh, landing?.flapReference?.risk],
      [".ar-gear", "起落架", landing?.gearPercent, landing?.aircraft?.gearIasKmh, landing?.gearRisk],
      [".ar-brake", "减速板", landing?.airbrakePercent, null, "reference"],
    ] as const) {
      const riskText = risk === "over-limit" ? "超限" : risk === "near-limit" ? "减速" : value == null ? "未知" : `${Math.round(value)}%`;
      const element = this.#text(selector, `${name} ${riskText}`, `${name}${limit ? `参考限速 IAS ${Math.round(limit)} km/h` : "限速未匹配"}`, risk ?? "unknown");
      element.hidden = value == null || value <= 0 || selector === ".ar-gear" && landing?.aircraft?.gearControl === false;
    }

    const rect = this.#canvas.getBoundingClientRect();
    const width = rect.width, height = rect.height, dpr = this.#view.devicePixelRatio || 1;
    if (!width || !height) return;
    if (this.#canvas.width !== Math.round(width * dpr) || this.#canvas.height !== Math.round(height * dpr)) {
      this.#canvas.width = Math.round(width * dpr); this.#canvas.height = Math.round(height * dpr);
    }
    const ctx = this.#context;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, width, height);
    const cx = width / 2, cy = height / 2;
    const halfW = Math.max(1, cx - 21), halfH = Math.max(1, cy - 60);
    const ppm = Math.min(halfW, halfH) / (rangeKm * 1000);
    ctx.save(); ctx.beginPath(); ctx.rect(0, 0, width, height); ctx.clip();
    const player = snapshot.navigation?.player, scale = snapshot.navigation?.mapScaleM;
    if (situation.available && player && scale && this.#paintBasemap) {
      ctx.save(); ctx.translate(cx, cy); ctx.rotate((this.#headingUp ? -snapshot.flight.headingDeg : 0) * Math.PI / 180);
      ctx.globalAlpha = .55;
      this.#paintBasemap(ctx, { x: -player.x * scale[0] * ppm, y: -player.y * scale[1] * ppm, width: scale[0] * ppm, height: scale[1] * ppm });
      ctx.restore();
    }
    ctx.strokeStyle = "#7299ae30"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, cy); ctx.lineTo(width, cy); ctx.moveTo(cx, 0); ctx.lineTo(cx, height); ctx.stroke();
    if (situation.available) {
      ctx.save(); ctx.font = "10px sans-serif"; ctx.textAlign = "center";
      for (const ring of airMapRings(ppm, Math.max(1, Math.min(cx, cy) - 36))) {
        ctx.strokeStyle = "rgba(180, 210, 224, .24)"; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.arc(cx, cy, ring.radiusPx, 0, Math.PI * 2); ctx.stroke();
        const offset = ring.radiusPx / Math.SQRT2;
        ctx.strokeStyle = "#071923"; ctx.lineWidth = 3; ctx.fillStyle = "#b4cedbcc";
        ctx.strokeText(ring.label, cx + offset, cy + offset + 3); ctx.fillText(ring.label, cx + offset, cy + offset + 3);
      }
      ctx.restore();
    }
    const labels: { x: number; y: number; width: number }[] = [];
    const zoneLabels: { x: number; y: number; width: number; text: string; color: string }[] = [];
    for (const zone of situation.zones) {
      const offset = airMapOffset(zone.eastM, zone.southM, snapshot.flight.headingDeg, this.#headingUp);
      const marker = airMapMarker(offset.x * ppm, offset.y * ppm, halfW, halfH);
      const x = cx + marker.x, y = cy + marker.y;
      ctx.save(); ctx.translate(x, y);
      ctx.strokeStyle = ctx.fillStyle = zone.item.friendly ? "#79c8ff" : "#ff4054";
      ctx.lineWidth = 1.5;
      drawBombingZoneSymbol(ctx, 6);
      if (marker.outside) {
        ctx.rotate(marker.angle); ctx.beginPath(); ctx.moveTo(9, -4); ctx.lineTo(14, 0); ctx.lineTo(9, 4); ctx.stroke();
      }
      ctx.restore();
      const text = `战区 ${zone.distanceKm.toFixed(1)} km`;
      ctx.font = "9px sans-serif"; ctx.textAlign = "center";
      const textWidth = ctx.measureText(text).width;
      const label = { x: Math.max(textWidth / 2 + 4, Math.min(width - textWidth / 2 - 4, x)),
        y: y + (marker.y > 0 ? -12 : 19), width: textWidth };
      zoneLabels.push({ ...label, text, color: zone.item.friendly ? "#79c8ff" : "#ff4054" });
    }
    const markers = situation.contacts.map((contact, index) => {
      const offset = airMapOffset(contact.eastM, contact.southM, snapshot.flight.headingDeg, this.#headingUp);
      const motion = motions[index];
      return { contact, motion, trailVisible: false, angle: airMapAircraftAngle(contact.item, motion?.velocity, snapshot.flight.headingDeg, this.#headingUp),
        color: airContactColor(contact.distanceKm), marker: airMapMarker(offset.x * ppm, offset.y * ppm, halfW, halfH) };
    });
    // Fading horizontal history. A vanished or unmatched contact has no samples.
    ctx.save(); ctx.beginPath(); ctx.rect(cx - halfW, cy - halfH, halfW * 2, halfH * 2); ctx.clip();
    ctx.lineWidth = 1.8; ctx.lineJoin = "round"; ctx.lineCap = "round";
    let visibleTrails = 0;
    for (const entry of markers.slice(0, 6)) {
      const { motion, color, marker } = entry;
      if (marker.outside) continue;
      const trail = motion?.trail ?? [];
      if (trail.length < 2) continue;
      let drawn = false;
      for (let index = 1; index < trail.length; index++) {
        const from = trail[index - 1]!, to = trail[index]!;
        const step = (from.ageMs - to.ageMs) / 1000;
        if (step <= 0 || step > 1.5 || Math.hypot(to.eastM - from.eastM, to.southM - from.southM) > 900 * step + 40) continue;
        const start = airMapOffset(from.eastM, from.southM, snapshot.flight.headingDeg, this.#headingUp);
        const end = airMapOffset(to.eastM, to.southM, snapshot.flight.headingDeg, this.#headingUp);
        if (Math.hypot(end.x - start.x, end.y - start.y) * ppm < .5) continue;
        ctx.globalAlpha = .1 + .55 * (1 - to.ageMs / AIR_CONTACT_TRAIL_MS); ctx.strokeStyle = color;
        ctx.beginPath(); ctx.moveTo(cx + start.x * ppm, cy + start.y * ppm); ctx.lineTo(cx + end.x * ppm, cy + end.y * ppm); ctx.stroke();
        drawn = true;
      }
      entry.trailVisible = drawn;
      if (drawn) visibleTrails++;
    }
    ctx.restore();
    // Paint all links underneath symbols and labels so crossings never cover them.
    ctx.save(); ctx.globalAlpha = .2; ctx.lineWidth = 1;
    for (const { marker, color } of markers) {
      ctx.strokeStyle = color;
      ctx.setLineDash(marker.outside ? [4, 4] : []);
      ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(cx + marker.x, cy + marker.y); ctx.stroke();
    }
    ctx.restore();
    let outsideCount = 0;
    let contactLabels = 0;
    for (const [index, { contact, marker, motion, angle, color }] of markers.entries()) {
      const x = cx + marker.x, y = cy + marker.y;
      ctx.fillStyle = color; ctx.strokeStyle = "#081822"; ctx.lineWidth = 2;
      ctx.save(); ctx.translate(x, y);
      if (marker.outside) {
        outsideCount++;
        ctx.save(); ctx.rotate(marker.angle);
        ctx.beginPath(); ctx.moveTo(12, -5); ctx.lineTo(17, 0); ctx.lineTo(12, 5);
        ctx.lineWidth = 4; ctx.stroke(); ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke(); ctx.restore();
      }
      ctx.save();
      ctx.rotate(angle ?? 0);
      ctx.scale(.65, .65);
      drawAircraftMapSymbol(ctx, contact.item.officialIcon);
      ctx.restore();
      if (motion?.suspectedGroup) {
        ctx.strokeStyle = color; ctx.globalAlpha = .55; ctx.lineWidth = 1; ctx.setLineDash([2, 3]);
        ctx.beginPath(); ctx.arc(0, 0, 13, 0, Math.PI * 2); ctx.stroke();
      }
      ctx.restore();
      if (contactLabels >= 6 || (index >= 6 && !motion?.groupSize) || (motion?.suspectedGroup && !motion.groupSize)) continue;
      const distanceText = `${motion?.groupSize ? `同向×${motion.groupSize} · ` : ""}${contact.distanceKm.toFixed(1)} km`;
      ctx.font = "9px sans-serif"; ctx.textAlign = "center";
      {
        const text = distanceText;
        const textWidth = ctx.measureText(text).width;
        const length = Math.hypot(marker.x, marker.y);
        const candidates = length > 75 ? [.7, .45].map(t => ({
          x: cx + marker.x * t - marker.y / length * 12,
          y: cy + marker.y * t + marker.x / length * 12 + 4,
        })) : [];
        candidates.push(
          { x, y: y + (y > cy ? -20 : 24) },
          { x, y: y + (y > cy ? 24 : -20) },
          { x: x + textWidth / 2 + 15, y: y + 4 },
          { x: x - textWidth / 2 - 15, y: y + 4 },
        );
        const label = candidates.map(candidate => ({
          x: Math.max(textWidth / 2 + 4, Math.min(width - textWidth / 2 - 4, candidate.x)), y: candidate.y,
        })).find(candidate => candidate.y >= 65 && candidate.y <= height - 60
          && !labels.some(other => Math.abs(other.x - candidate.x) < (other.width + textWidth) / 2 + 5 && Math.abs(other.y - candidate.y) < 15)
          && !markers.some(other => Math.abs(cx + other.marker.x - candidate.x) < textWidth / 2 + 12 && Math.abs(cy + other.marker.y - candidate.y + 4) < 17)
          && !(Math.abs(cx - candidate.x) < textWidth / 2 + 10 && Math.abs(cy - candidate.y + 4) < 17));
        if (label) {
          labels.push({ ...label, width: textWidth });
          contactLabels++;
          ctx.strokeStyle = "#071923"; ctx.lineWidth = 3; ctx.strokeText(text, label.x, label.y); ctx.fillText(text, label.x, label.y);
        }
      }
    }
    // Keep measured closure with the observed trail, separate from range at the
    // aircraft. Side offsets leave even a short trail intact and never invent it.
    ctx.font = "9px sans-serif"; ctx.textAlign = "center";
    for (const { motion, marker, color, trailVisible } of markers.slice(0, 3)) {
      const text = airContactClosingLabel(motion?.closingMps ?? null);
      const trail = motion?.trail ?? [];
      if (!text || marker.outside || !trailVisible) continue;
      const points = trail.map(point => {
        const offset = airMapOffset(point.eastM, point.southM, snapshot.flight.headingDeg, this.#headingUp);
        return { x: cx + offset.x * ppm, y: cy + offset.y * ppm };
      });
      const start = points[0]!, end = points[points.length - 1]!;
      const dx = end.x - start.x, dy = end.y - start.y, length = Math.hypot(dx, dy);
      const nx = length > .5 ? -dy / length : 1, ny = length > .5 ? dx / length : 0;
      const textWidth = ctx.measureText(text).width;
      const candidates = [.35, 0, .65].flatMap(fraction => {
        const point = points[Math.round((points.length - 1) * fraction)]!;
        return [-1, 1].map(side => ({ x: point.x + side * nx * (textWidth / 2 + 8), y: point.y + side * ny * 14 + 4 }));
      });
      const label = candidates.find(candidate => candidate.x >= textWidth / 2 + 4 && candidate.x <= width - textWidth / 2 - 4
        && candidate.y >= 65 && candidate.y <= height - 60
        && !labels.some(other => Math.abs(other.x - candidate.x) < (other.width + textWidth) / 2 + 5 && Math.abs(other.y - candidate.y) < 15)
        && !markers.some(other => Math.abs(cx + other.marker.x - candidate.x) < textWidth / 2 + 10 && Math.abs(cy + other.marker.y - candidate.y + 4) < 14)
        && !(Math.abs(cx - candidate.x) < textWidth / 2 + 10 && Math.abs(cy - candidate.y + 4) < 17));
      if (!label) continue;
      ctx.strokeStyle = "#071923"; ctx.lineWidth = 3; ctx.fillStyle = color;
      ctx.strokeText(text, label.x, label.y); ctx.fillText(text, label.x, label.y);
      labels.push({ ...label, width: textWidth });
    }
    // Zone labels yield to aircraft distance/closure annotations; their symbols
    // remain visible even when the compact view has no room for text.
    ctx.font = "9px sans-serif"; ctx.textAlign = "center";
    for (const zone of zoneLabels) {
      const y = [zone.y, zone.y + 16, zone.y - 32].find(candidate => candidate >= 65 && candidate <= height - 60
        && !labels.some(other => Math.abs(other.x - zone.x) < (other.width + zone.width) / 2 + 5 && Math.abs(other.y - candidate) < 15)
        && !markers.some(other => Math.abs(cx + other.marker.x - zone.x) < zone.width / 2 + 12 && Math.abs(cy + other.marker.y - candidate + 4) < 17)
        && !(Math.abs(cx - zone.x) < zone.width / 2 + 10 && Math.abs(cy - candidate + 4) < 17));
      if (y === undefined) continue;
      ctx.strokeStyle = "#071923"; ctx.lineWidth = 3; ctx.fillStyle = zone.color;
      ctx.strokeText(zone.text, zone.x, y); ctx.fillText(zone.text, zone.x, y);
      labels.push({ x: zone.x, y, width: zone.width });
    }
    // Friendlies neither control zoom nor reserve label space. Keep only small
    // in-view symbols, yielding to every enemy symbol/label and the ownship.
    const friendlyMarkers: { x: number; y: number }[] = [];
    const friendlyLimit = markers.length >= 6 ? 6 : 12;
    const teammates = [...situation.teammates].sort((a, b) => Math.hypot(a.eastM, a.southM) - Math.hypot(b.eastM, b.southM));
    for (const contact of teammates) {
      if (friendlyMarkers.length >= friendlyLimit) break;
      const offset = airMapOffset(contact.eastM, contact.southM, snapshot.flight.headingDeg, this.#headingUp);
      const x = cx + offset.x * ppm, y = cy + offset.y * ppm;
      if (x < 12 || x > width - 12 || y < 65 || y > height - 60
        || Math.hypot(x - cx, y - cy) < 18
        || markers.some(other => Math.hypot(cx + other.marker.x - x, cy + other.marker.y - y) < 24)
        || labels.some(label => Math.abs(label.x - x) < label.width / 2 + 10 && Math.abs(label.y - 4 - y) < 16)
        || friendlyMarkers.some(other => Math.hypot(other.x - x, other.y - y) < 16)) continue;
      ctx.save(); ctx.translate(x, y);
      ctx.rotate(airMapAircraftAngle(contact.item, null, snapshot.flight.headingDeg, this.#headingUp) ?? 0);
      ctx.scale(.55, .55); ctx.globalAlpha = .35;
      ctx.fillStyle = "#79c8ff"; ctx.strokeStyle = "#071923"; ctx.lineWidth = 2;
      drawAircraftMapSymbol(ctx, contact.item.officialIcon); ctx.restore();
      friendlyMarkers.push({ x, y });
    }
    this.#canvas.dataset.friendlies = String(friendlyMarkers.length);
    this.#canvas.dataset.contacts = String(situation.contacts.length);
    this.#canvas.dataset.outside = String(outsideCount);
    this.#canvas.dataset.suspectedGroups = String(motions.filter(motion => motion.groupSize > 0).length);
    this.#canvas.dataset.trails = String(visibleTrails);
    ctx.restore();
    ctx.font = "10px sans-serif"; ctx.textAlign = "center"; ctx.fillStyle = "#b5c9d5";
    const north = airMapOffset(0, -1, snapshot.flight.headingDeg, this.#headingUp);
    const n = airMapMarker(north.x * 100000, north.y * 100000, halfW - 10, halfH - 10);
    ctx.fillText("N", cx + n.x, cy + n.y + 3);
    if (situation.available) {
      if (vector) {
        const angle = (vector.headingDeg - (this.#headingUp ? snapshot.flight.headingDeg : 0)) * Math.PI / 180;
        ctx.save(); ctx.translate(cx, cy); ctx.rotate(angle);
        ctx.lineCap = "round"; ctx.lineJoin = "round";
        ctx.beginPath(); ctx.moveTo(0, -15); ctx.lineTo(0, -58);
        ctx.moveTo(-6, -49); ctx.lineTo(0, -58); ctx.lineTo(6, -49);
        ctx.strokeStyle = "#071923"; ctx.lineWidth = 6; ctx.stroke();
        ctx.strokeStyle = "#ffe16a"; ctx.lineWidth = 3; ctx.stroke(); ctx.restore();
      }
      ctx.save(); ctx.translate(cx, cy); ctx.rotate((this.#headingUp ? 0 : snapshot.flight.headingDeg) * Math.PI / 180);
      ctx.fillStyle = "#eff9ff"; ctx.strokeStyle = "#062131"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(0, -9); ctx.lineTo(6, 7); ctx.lineTo(0, 3); ctx.lineTo(-6, 7); ctx.closePath(); ctx.fill(); ctx.stroke(); ctx.restore();
    } else { ctx.fillStyle = "#e6c38c"; ctx.fillText(situation.reason, cx, cy); }
    ctx.textAlign = "start";
  }
}
