import type { EditionPolicy } from "./edition-policy";
import type { Official8111Frame } from "./telemetry-source";
import { normalizeOfficialMapInfo } from "./map-info";
import { GroundTrackEstimator, type GroundTrackEstimate } from "./ground-track";
import { FuelManager, fuelEngines, fuelNumber } from "./fuel-management";
import type { AircraftParameters } from "./aircraft-parameters";
import { LandingAssist } from "./landing-assist";
import { landingFlapReference } from "./landing-configuration";
import { RESET_UNDO_WINDOW_MS, sortieMapSignature, type SortieRecoveryStore, type SortieResetReason,
  type SortieResetUndoRecord, type SortieRestorePoint } from "./sortie-recovery";
import type { RuntimePhase, NavigationSelectionMode, RuntimeSettings, RuntimeSettingsStore,
  TimerCheckpoint, TimerCheckpointStore, NavigationItem, EditionSnapshot, EditionCommand,
  ParsedTelemetry, ParsedMap, PlayerFlightEvidence, StrikeTargetMode, StrikeAirfieldModule } from "./runtime-types";
export type * from "./runtime-types";

export interface PublicRuntimeOptions {
    edition: EditionPolicy;
    settingsStore?: RuntimeSettingsStore;
    timerCheckpointStore?: TimerCheckpointStore | null;
    sortieRecoveryStore?: SortieRecoveryStore | null;
    now?: () => number;
    aircraftParameters?: AircraftParameters | null;
  }

const DEFAULT_CHECKLIST = [
  "按 I 启动发动机",
  "检查襟翼 / 起落架",
  "开启增稳系统",
  "关闭武器选择模式",
  "Y66 设定打击目标",
  "Y67 开启 CCRP",
  "Y65 关闭座舱盖",
] as const;

const NO_DATA_GRACE_MS = 12_000;
const LANDING_EVIDENCE_MAX_AGE_MS = 1_500;
const GROUND_CONTINUITY_MAX_MS = 60_000;
const LOW_ENERGY_APPROACH_MAX_IAS_KMH = 180;
const LOW_ENERGY_APPROACH_MAX_VERTICAL_SPEED_MPS = 8;
const LOW_ENERGY_APPROACH_MIN_GEAR_PERCENT = 50;

export class MemoryRuntimeSettingsStore implements RuntimeSettingsStore {
  value: Partial<RuntimeSettings> | null;
  constructor(value: Partial<RuntimeSettings> | null = null) { this.value = value; }
  load(): Partial<RuntimeSettings> | null { return this.value; }
  save(settings: RuntimeSettings): void { this.value = structuredClone(settings); }
}

export class BrowserRuntimeSettingsStore implements RuntimeSettingsStore {
  readonly #key: string;
  readonly #storage: Storage;
  constructor(channel: string, storage: Storage = localStorage) {
    this.#key = `bomana:browser-runtime:v1:${channel}`;
    this.#storage = storage;
  }
  load(): Partial<RuntimeSettings> | null {
    try {
      const value = this.#storage.getItem(this.#key);
      return value ? JSON.parse(value) as Partial<RuntimeSettings> : null;
    } catch {
      return null;
    }
  }
  save(settings: RuntimeSettings): void { this.#storage.setItem(this.#key, JSON.stringify(settings)); }
}

export class MemoryTimerCheckpointStore implements TimerCheckpointStore {
  value: unknown = null;
  load(): unknown { return structuredClone(this.value); }
  save(checkpoint: TimerCheckpoint): void { this.value = structuredClone(checkpoint); }
  clear(): void { this.value = null; }
}

export class BrowserTimerCheckpointStore implements TimerCheckpointStore {
  readonly #key: string;
  readonly #storage: Storage;
  constructor(channel: string, storage: Storage = localStorage) {
    this.#key = `bomana:timer-checkpoint:v1:${channel}`;
    this.#storage = storage;
  }
  load(): unknown {
    try {
      const value = this.#storage.getItem(this.#key);
      return value ? JSON.parse(value) : null;
    } catch {
      return null;
    }
  }
  save(checkpoint: TimerCheckpoint): void {
    try { this.#storage.setItem(this.#key, JSON.stringify(checkpoint)); } catch { /* Timer remains usable in memory. */ }
  }
  clear(): void {
    try { this.#storage.removeItem(this.#key); } catch { /* Private storage may be unavailable. */ }
  }
}

export class PublicRuntime {
  protected readonly _edition: EditionPolicy;
  protected readonly _settingsStore: RuntimeSettingsStore;
  protected readonly _timerCheckpointStore: TimerCheckpointStore | null;
  protected readonly _sortieRecoveryStore: SortieRecoveryStore | null;
  protected readonly _now: () => number;
  protected readonly _aircraftParameters: AircraftParameters | null;
  protected readonly _fuel: FuelManager;
  protected readonly _landing = new LandingAssist();
  protected _landingAircraft = "";
  protected _settings: RuntimeSettings;
  protected _phase: RuntimePhase = "idle";
  protected _candidateSinceMs: number | null = null;
  protected _lifeStartedAtMs: number | null = null;
  protected _lifeIndex = 0;
  protected _revision = 0;
  protected _checklistChecked: boolean[];
  protected _lastFrame: Official8111Frame | null = null;
  protected _lastPlayerPoint: { readonly x: number; readonly y: number } | null = null;
  protected _lastPlayerFlightEvidence: PlayerFlightEvidence | null = null;
  protected _groundContinuitySinceMs: number | null = null;
  protected _automaticNavigationTargetId: string | null = null;
  protected _navigationSelectionMode: NavigationSelectionMode = "auto";
  protected _lastTimerCheckpointAtMs = 0;
  protected _lastSortieRecoveryAtMs = 0;
  protected _noDataSinceMs: number | null = null;
  protected _lifecycleEvidenceMissingSinceMs: number | null = null;
  protected _resetSuppressedUntilEvidence = false;
  protected _resetUndo: SortieResetUndoRecord | null = null;
  protected _pendingSortieResume: SortieRestorePoint | null = null;
  protected _currentMapSignature = "";
  protected readonly _groundTrack = new GroundTrackEstimator();
  protected _groundTrackEstimate: GroundTrackEstimate | null = null;
  protected _lastSnapshot: EditionSnapshot;

  constructor(options: PublicRuntimeOptions) {
    this._edition = options.edition;
    this._settingsStore = options.settingsStore ?? new MemoryRuntimeSettingsStore();
    this._timerCheckpointStore = options.timerCheckpointStore ?? null;
    this._sortieRecoveryStore = options.sortieRecoveryStore ?? null;
    this._now = options.now ?? Date.now;
    this._aircraftParameters = options.aircraftParameters ?? null;
    this._fuel = new FuelManager(this._aircraftParameters);
    this._settings = { ...normalizeSettings(this._settingsStore.load()), selectedNavigationId: null };
    this._checklistChecked = this._settings.checklistItems.map(() => false);
    const nowMs = this._now();
    const recovery = this._sortieRecoveryStore?.load(nowMs, this._settings.cycleMinutes * 60) ?? null;
    this._resetUndo = recovery?.resetUndo ?? null;
    this._pendingSortieResume = this._resetUndo ? null : recovery?.resume ?? null;
    const storedTimer = this._timerCheckpointStore?.load();
    const restoredTimer = normalizeTimerCheckpoint(
      storedTimer,
      this._settings.cycleMinutes * 60,
      nowMs,
    );
    if (storedTimer !== null && storedTimer !== undefined && !restoredTimer) {
      this._timerCheckpointStore?.clear();
    }
    if (restoredTimer) {
      this._phase = restoredTimer.phase;
      this._lifeStartedAtMs = restoredTimer.lifeStartedAtMs;
      this._lifeIndex = restoredTimer.lifeIndex;
      this._lastTimerCheckpointAtMs = restoredTimer.savedAtMs;
    }
    if (this._resetUndo) {
      this._phase = "wait-next";
      this._lifeStartedAtMs = null;
    }
    this._lastSnapshot = emptySnapshot(this._edition, this._settings);
    if (restoredTimer) {
      this._lastSnapshot = Object.freeze({
        ...this._lastSnapshot,
        sampledAtMs: this._now(),
        phase: this._phase,
        timer: this._buildTimer(this._now()),
      });
    }
    if (this._resetUndo) {
      this._lastSnapshot = Object.freeze({
        ...this._lastSnapshot,
        sampledAtMs: nowMs,
        phase: "wait-next",
        timer: this._buildTimer(nowMs),
        sortieContinuity: this._buildSortieContinuity(nowMs),
      });
    }
  }

  snapshot(): EditionSnapshot {
    this._expireResetUndo(this._now());
    return this._lastSnapshot;
  }

  saveTimerCheckpoint(nowMs = this._now()): void {
    this._persistTimerCheckpoint(nowMs, true);
    this._persistSortieRecovery(nowMs, true);
  }

  async ingest(frame: Official8111Frame): Promise<EditionSnapshot> {
    this._lastFrame = frame;
    this._expireResetUndo(frame.sampledAtMs);
    const telemetry = parseTelemetry(frame);
    const map = this._parseMap(frame.mapObjects);
    const frameHeld = Object.values(frame.holdover ?? {}).some(Boolean);
    const mapSignature = sortieMapSignature(frame.mapInfo);
    if (mapSignature) {
      if (this._currentMapSignature && mapSignature !== this._currentMapSignature) {
        this._fuel.reset();
        this._groundTrack.reset();
        this._groundTrackEstimate = null;
        this._resetExtension("map");
      }
      this._currentMapSignature = mapSignature;
      this._reconcilePendingSortieResume(mapSignature);
    }
    const mapScale = parseMapScale(frame.mapInfo);
    const mapObservedAtMs = frame.mapObjectsSampledAtMs ?? frame.sampledAtMs;
    if (map.player && mapScale && !frameHeld) {
      this._groundTrackEstimate = this._groundTrack.update({
        atMs: mapObservedAtMs,
        x: map.player.x,
        y: map.player.y,
        scale: mapScale,
      });
    } else if (!frameHeld) {
      this._groundTrack.reset();
      this._groundTrackEstimate = null;
    }
    this._updateLifecycle(frame, telemetry, map);
    this._persistTimerCheckpoint(frame.sampledAtMs);
    this._persistSortieRecovery(frame.sampledAtMs);
    const sortieContinuity = this._buildSortieContinuity(frame.sampledAtMs);
    const zoneObservedAtMs = frame.mapObjectsSampledAtMs ?? frame.sampledAtMs;
    this._observeExtension(frame, map, sortieContinuity);
    const fuelLive = this._phase === "alive" && sortieContinuity.state === "live"
      && frame.availability.state && frame.holdover?.state !== true && frame.state?.valid !== false;
    if (this._edition.capabilities.fuel && fuelLive) {
      const state = frame.state ?? {};
      this._fuel.observe({
        atMs: frame.stateSampledAtMs ?? frame.sampledAtMs, aircraft: telemetry.aircraft,
        fuelKg: fuelNumber(state, ["Mfuel, kg", "Mfuel", "fuel"]),
        initialKg: fuelNumber(state, ["Mfuel0, kg", "Mfuel0", "fuel0"]),
        engines: fuelEngines(state), altitudeM: telemetry.altitudeM,
        tasKmh: telemetry.tasObserved ? telemetry.tasKmh : null, iasKmh: telemetry.iasKmh,
        verticalSpeedMps: telemetry.verticalSpeedMps, onGround: telemetry.onGround,
        groundSpeedKmh: this._groundTrackEstimate?.valid ? this._groundTrackEstimate.groundSpeedMps * 3.6 : null,
      });
    }
    const headingDeg = telemetry.headingDeg ?? mapHeading(map.player);
    let navigation = this._buildNavigation(frame, map, headingDeg);
    if (sortieContinuity.state !== "live" && sortieContinuity.state !== "reset-undo" && !navigation?.player) {
      navigation = this._buildContinuityNavigation(navigation);
    }
    const fuel = this._buildFuel(navigation, frame.sampledAtMs, fuelLive);
    const stateNumber = (keys: readonly string[]) => optionalNumericField(frame.state ?? {}, keys);
    const landing = this._buildLandingSnapshot(frame, telemetry, navigation, sortieContinuity, frameHeld, frame.sampledAtMs);
    const extension = this._snapshotExtension(telemetry, navigation, headingDeg, sortieContinuity);
    this._revision += 1;
    const timer = this._buildTimer(frame.sampledAtMs);
    const speedStateFresh = frame.availability.state && frame.availability.indicators
      && !frame.holdover?.state && !frame.holdover?.indicators
      && frame.state?.valid !== false && frame.indicators?.valid === true
      && [frame.stateSampledAtMs, frame.indicatorsSampledAtMs]
        .every(at => at == null || frame.sampledAtMs - at <= 1500);
    const observedIas = stateNumber(["IAS, km/h", "IAS", "ias"]);
    const overspeed = evaluateOverspeed(
      telemetry.aircraft,
      telemetry.iasKmh,
      telemetry.mach,
      this._aircraftParameters,
      optionalNumericField(frame.indicators ?? {}, ["wing_sweep_indicator", "wing_sweep", "sweep"]),
      speedStateFresh && observedIas !== null && observedIas >= 0 ? stateNumber(["flaps, %", "flaps"]) : null,
    );
    const alerts: string[] = [];
    if (this._edition.capabilities.missionAlerts) {
      if (!frame.availability.state || !frame.availability.indicators || !frame.availability.mapObjects) {
        alerts.push("游戏数据暂不完整");
      }
      if (sortieContinuity.state === "reset-undo") alerts.push("出击状态已重置，可在 30 秒内撤销");
      if (overspeed.level === "critical") alerts.push("空速危险");
      else if (overspeed.level === "warning") alerts.push(overspeed.iasLimitSource === "flaps" && overspeed.ratio >= .97
        ? "接近襟翼参考限速" : "接近结构限速");
      if (!landing?.settings.enabled && telemetry.gearPercent > 50 && telemetry.iasKmh > 80) alerts.push("起落架未收起");
      alerts.push(...this._extensionAlerts(frame.sampledAtMs));
    }
    this._lastSnapshot = Object.freeze({
      edition: this._edition,
      revision: this._revision,
      sampledAtMs: frame.sampledAtMs,
      mapObjectsSampledAtMs: zoneObservedAtMs,
      connected: frame.availability.indicators && frame.availability.state && frame.availability.mapObjects,
      weaponRelease: this._edition.capabilities.strikePrediction ? {
        machLimits: this._aircraftParameters?.releaseMach(telemetry.aircraft, this._settings.selectedWeaponId) ?? null,
        mach: speedStateFresh && sortieContinuity.state === "live" ? telemetry.mach : null,
        tasKmh: speedStateFresh && sortieContinuity.state === "live" && telemetry.tasObserved ? telemetry.tasKmh : null,
      } : null,
      phase: this._phase,
      sortieContinuity,
      timer,
      flight: Object.freeze({
        aircraft: telemetry.aircraft,
        altitudeM: telemetry.altitudeM,
        iasKmh: telemetry.iasKmh,
        tasKmh: telemetry.tasKmh,
        tasObserved: telemetry.tasObserved,
        verticalSpeedMps: telemetry.verticalSpeedMps,
        headingDeg,
        mach: telemetry.mach,
        gearPercent: telemetry.gearPercent,
        onGround: telemetry.onGround,
        overspeed,
      }),
      navigation,
      ...extension,
      fuel,
      landing,
      checklist: this._edition.capabilities.checklist
        ? Object.freeze({
            items: this._settings.checklistItems,
            checked: Object.freeze([...this._checklistChecked]),
          })
        : null,
      alerts: Object.freeze(alerts),
    });
    return this._lastSnapshot;
  }

  async command(command: EditionCommand): Promise<EditionSnapshot> {
    const commandNowMs = this._now();
    this._expireResetUndo(commandNowMs);
    switch (command.type) {
      case "landing.configure":
        if (!this._edition.capabilities.airfieldNavigation) throw new Error("landing assistance is disabled in this edition");
        this._landing.configure(command.landing, this._lastSnapshot.navigation);
        break;
      case "timer.reset":
        this._lifeStartedAtMs = this._now();
        this._resetUndo = null;
        this._resetSuppressedUntilEvidence = false;
        this._clearGroundContinuity();
        if (this._phase !== "alive") {
          this._phase = "alive";
          this._lifeIndex += 1;
        }
        this._persistTimerCheckpoint(this._lifeStartedAtMs, true);
        // A manual restart clears the previous ground-continuity evidence. If
        // the latest authoritative map already has no player, preserve the
        // existing loss/undo contract without replaying the full frame into
        // fuel, track, chat, or zone-history observers.
        this._projectLossAfterTimerReset(commandNowMs);
        break;
      case "timer.set-cycle":
        if (!Number.isInteger(command.minutes) || command.minutes < 1 || command.minutes > 180) {
          throw new TypeError("timer cycle must be an integer from 1 through 180");
        }
        this._settings = { ...this._settings, cycleMinutes: command.minutes };
        this._persistTimerCheckpoint(this._now(), true);
        break;
      case "navigation.select":
        if (!this._edition.capabilities.zoneNavigation && !this._edition.capabilities.airfieldNavigation) {
          throw new Error("navigation is disabled in this edition");
        }
        if (command.targetId === null) {
          this._navigationSelectionMode = "paused";
          this._settings = { ...this._settings, selectedNavigationId: null };
          break;
        }
        {
          const target = this._lastSnapshot.navigation?.items.find((item) => item.id === command.targetId);
          if (!target) throw new Error("navigation target is unavailable");
          this._navigationSelected(target);
          this._navigationSelectionMode = "locked";
          this._settings = { ...this._settings, selectedNavigationId: command.targetId };
        }
        break;
      case "navigation.clear-selection":
        if (!this._edition.capabilities.zoneNavigation && !this._edition.capabilities.airfieldNavigation) {
          throw new Error("navigation is disabled in this edition");
        }
        this._navigationSelectionMode = "auto";
        this._settings = {
          ...this._settings,
          selectedNavigationId: null,
          strikeTargetMode: "auto",
        };
        break;
      case "navigation.resume-auto":
        if (!this._edition.capabilities.zoneNavigation && !this._edition.capabilities.airfieldNavigation) {
          throw new Error("navigation is disabled in this edition");
        }
        this._navigationSelectionMode = "auto";
        this._settings = { ...this._settings, selectedNavigationId: null, strikeTargetMode: "auto" };
        break;
      case "checklist.set": {
        if (!this._edition.capabilities.checklist) throw new Error("checklist is disabled in this edition");
        const items = normalizeChecklist(command.items);
        this._settings = { ...this._settings, checklistItems: items };
        this._checklistChecked = items.map(() => false);
        break;
      }
      case "checklist.toggle":
        if (!this._edition.capabilities.checklist) throw new Error("checklist is disabled in this edition");
        if (!Number.isInteger(command.index) || command.index < 0 || command.index >= this._checklistChecked.length) {
          throw new TypeError("checklist index is invalid");
        }
        this._checklistChecked[command.index] = !this._checklistChecked[command.index];
        break;
      case "sortie.undo-reset":
        return this._undoSortieReset(commandNowMs);
      default:
        if (!this._extensionCommand(command)) throw new Error("command is disabled in this edition");
    }
    this._afterCommand(command);
    this._settingsStore.save(this._settings);
    this._persistSortieRecovery(commandNowMs, true);
    return this._projectCommandSnapshot(commandNowMs);
  }

  /**
   * Rebuild the command-facing view from the most recent observation without
   * feeding that observation through lifecycle, fuel, chat or zone-history
   * consumers a second time. A command can invalidate a completed strike, so
   * the projected view intentionally carries no strike result until a newer
   * telemetry sample and solver pass establish one.
   */
  protected _projectCommandSnapshot(nowMs: number): EditionSnapshot {
    const previous = this._lastSnapshot;
    const frame = this._lastFrame;
    if (!frame) {
      const continuity = this._buildSortieContinuity(nowMs);
      const extension = this._projectCommandExtension(null, previous.navigation, previous.flight.headingDeg, continuity);
      this._revision += 1;
      this._lastSnapshot = Object.freeze({
        ...previous,
        revision: this._revision,
        phase: this._phase,
        timer: this._buildTimer(nowMs),
        sortieContinuity: continuity,
        ...extension,
        strike: null,
        alerts: this._projectCommandAlerts(previous.alerts, previous.flight, previous.landing),
        checklist: this._edition.capabilities.checklist
          ? Object.freeze({ items: this._settings.checklistItems, checked: Object.freeze([...this._checklistChecked]) })
          : null,
      });
      return this._lastSnapshot;
    }

    const telemetry = parseTelemetry(frame);
    const map = this._parseMap(frame.mapObjects);
    const frameHeld = Object.values(frame.holdover ?? {}).some(Boolean);
    const continuity = this._buildSortieContinuity(nowMs);
    const headingDeg = telemetry.headingDeg ?? mapHeading(map.player);
    let navigation = previous.navigation;
    if (previous.connected && !frameHeld) {
      navigation = this._buildNavigation(frame, map, headingDeg);
      if (continuity.state !== "live" && continuity.state !== "reset-undo" && !navigation?.player) {
        navigation = this._buildContinuityNavigation(navigation);
      }
    }
    const fuelLive = this._phase === "alive" && continuity.state === "live"
      && frame.availability.state && frame.holdover?.state !== true && frame.state?.valid !== false;
    const landing = this._buildLandingSnapshot(frame, telemetry, navigation, continuity, frameHeld, nowMs, true);
    const extension = this._projectCommandExtension(telemetry, navigation, headingDeg, continuity);
    this._revision += 1;
    this._lastSnapshot = Object.freeze({
      ...previous,
      revision: this._revision,
      phase: this._phase,
      timer: this._buildTimer(nowMs),
      sortieContinuity: continuity,
      navigation,
      fuel: this._buildFuel(navigation, nowMs, fuelLive),
      landing,
      ...extension,
      strike: null,
      alerts: this._projectCommandAlerts(previous.alerts, previous.flight, landing),
      checklist: this._edition.capabilities.checklist
        ? Object.freeze({ items: this._settings.checklistItems, checked: Object.freeze([...this._checklistChecked]) })
        : null,
    });
    return this._lastSnapshot;
  }

  private _projectCommandAlerts(
    previous: readonly string[],
    flight: EditionSnapshot["flight"],
    landing: EditionSnapshot["landing"],
  ): readonly string[] {
    const alerts = previous.filter((alert) => alert !== "起落架未收起");
    if (this._edition.capabilities.missionAlerts && !landing?.settings.enabled && flight.gearPercent > 50 && flight.iasKmh > 80) {
      return Object.freeze([...alerts, "起落架未收起"]);
    }
    return Object.freeze([...alerts]);
  }

  protected _buildLandingSnapshot(
    frame: Official8111Frame,
    telemetry: ParsedTelemetry,
    navigation: EditionSnapshot["navigation"],
    continuity: EditionSnapshot["sortieContinuity"],
    frameHeld: boolean,
    nowMs: number,
    projectOnly = false,
  ): EditionSnapshot["landing"] {
    if (!this._edition.capabilities.airfieldNavigation) return null;
    if (!projectOnly && frame.availability.indicators && !frame.holdover?.indicators && frame.indicators?.valid === true && telemetry.aircraft) {
      this._landingAircraft = telemetry.aircraft;
    }
    const sourceTimes = [frame.stateSampledAtMs, frame.indicatorsSampledAtMs, frame.mapObjectsSampledAtMs];
    const fresh = continuity.state === "live" && !frameHeld && frame.availability.state
      && frame.availability.indicators && frame.availability.mapObjects && frame.state?.valid !== false
      && nowMs - frame.sampledAtMs <= 1_500
      && sourceTimes.every((at) => at == null || frame.sampledAtMs - at <= 1_500);
    const stateNumber = (keys: readonly string[]) => optionalNumericField(frame.state ?? {}, keys);
    const input = {
      sampledAtMs: frame.sampledAtMs,
      context: `${this._currentMapSignature}|${this._landingAircraft}|${this._lifeIndex}|${this._phase === "hangar" || this._phase === "wait-next" ? this._phase : "sortie"}`,
      fresh,
      navigation,
      track: this._groundTrackEstimate,
      aircraft: this._aircraftParameters?.landing(this._landingAircraft) ?? null,
      altitudeM: stateNumber(["H, m", "H", "altitude"]),
      iasKmh: stateNumber(["IAS, km/h", "IAS", "ias"]),
      verticalSpeedMps: stateNumber(["Vy, m/s", "Vy", "vy"]),
      gearPercent: stateNumber(["gear, %", "gear"]),
      airbrakePercent: stateNumber(["airbrake, %", "airbrake"]),
      flapsPercent: stateNumber(["flaps, %", "flaps"]),
    };
    return projectOnly ? this._landing.project(input, point => this._landingElevation(point))
      : this._landing.update(input, point => this._landingElevation(point));
  }

  protected _projectCommandExtension(
    _telemetry: ParsedTelemetry | null,
    _navigation: EditionSnapshot["navigation"],
    _heading: number,
    _continuity: EditionSnapshot["sortieContinuity"],
  ): Pick<EditionSnapshot, "destroyedZones" | "mapGrid" | "markedZones" | "gameChat" | "strikeSelection" | "strike"> {
    return {
      destroyedZones: this._lastSnapshot.destroyedZones,
      mapGrid: this._lastSnapshot.mapGrid,
      markedZones: this._lastSnapshot.markedZones,
      gameChat: this._lastSnapshot.gameChat,
      strikeSelection: this._lastSnapshot.strikeSelection,
      strike: null,
    };
  }

  protected _projectLossAfterTimerReset(nowMs: number): void {
    const frame = this._lastFrame;
    if (!frame || !frame.bridgeReachable || !frame.availability.mapObjects || frame.holdover?.mapObjects === true) return;
    if (this._parseMap(frame.mapObjects).player !== null) return;
    this._beginSortieReset(nowMs, "aircraft-loss");
  }

  protected _updateLifecycle(frame: Official8111Frame, telemetry: ParsedTelemetry, map: ParsedMap): void {
    const now = frame.sampledAtMs;
    const activeSortie = this._phase === "alive" || this._phase === "loss-pending";
    const dynamicStale = Object.values(frame.holdover ?? {}).some(Boolean)
      || !frame.availability.indicators
      || !frame.availability.state
      || !frame.availability.mapObjects;
    if (activeSortie && dynamicStale) {
      if (this._noDataSinceMs === null) this._noDataSinceMs = now;
    } else if (!dynamicStale) {
      this._noDataSinceMs = null;
    }
    const authoritativeMap = frame.bridgeReachable
      && frame.availability.mapObjects
      && frame.holdover?.mapObjects !== true;
    if (!authoritativeMap) {
      if (activeSortie) {
        if (this._lifecycleEvidenceMissingSinceMs === null) this._lifecycleEvidenceMissingSinceMs = now;
        if (
          now - this._lifecycleEvidenceMissingSinceMs >= NO_DATA_GRACE_MS
          && !this._resetSuppressedUntilEvidence
        ) this._beginSortieReset(now, "telemetry-timeout");
      }
      return;
    }
    this._lifecycleEvidenceMissingSinceMs = null;
    const playerPresent = map.player !== null;
    const currentStateEvidence = frame.availability.state && frame.holdover?.state !== true;
    const currentStateObservedAtMs = frame.stateSampledAtMs ?? now;
    if (map.player) {
      this._groundContinuitySinceMs = null;
      this._lastPlayerPoint = Object.freeze({ x: map.player.x, y: map.player.y });
      if (currentStateEvidence && telemetry.stateValid) {
        this._lastPlayerFlightEvidence = Object.freeze({
          sampledAtMs: currentStateObservedAtMs,
          iasKmh: telemetry.iasKmh,
          verticalSpeedMps: telemetry.verticalSpeedMps,
          gearPercent: telemetry.gearPercent,
          onGround: telemetry.onGround,
        });
      }
      this._resetSuppressedUntilEvidence = false;
    }
    const groundContinuity = !playerPresent && (
      (
        this._groundContinuitySinceMs !== null
        && now - this._groundContinuitySinceMs <= GROUND_CONTINUITY_MAX_MS
        && currentStateEvidence
        && telemetry.stateValid
        && telemetry.onGround
      )
      || (currentStateEvidence && hasGroundContinuity(
        telemetry,
        this._lastPlayerFlightEvidence,
        currentStateObservedAtMs,
      ))
    );
    if (!playerPresent) {
      if (groundContinuity && this._groundContinuitySinceMs === null) this._groundContinuitySinceMs = now;
      else if (!groundContinuity) this._groundContinuitySinceMs = null;
    }
    const spawnCandidate = playerPresent && telemetry.entityLike;
    const hangarLike = map.objectCount === 0;
    if (hangarLike && !playerPresent && this._phase !== "alive" && this._phase !== "loss-pending") {
      if (this._candidateSinceMs === null) this._candidateSinceMs = now;
      else if (now - this._candidateSinceMs >= 1_200) {
        this._phase = "hangar";
        this._lifeStartedAtMs = null;
        this._lifeIndex = 0;
        this._fuel.reset();
        this._resetExtension("hangar");
        this._lastPlayerPoint = null;
        this._clearGroundContinuity();
        this._automaticNavigationTargetId = null;
        this._navigationSelectionMode = "auto";
        this._settings = { ...this._settings, selectedNavigationId: null };
        this._timerCheckpointStore?.clear();
        this._lastTimerCheckpointAtMs = 0;
      }
      return;
    }
    if (this._phase === "idle" || this._phase === "hangar") {
      if (spawnCandidate) { this._phase = "arming"; this._candidateSinceMs = now; }
      return;
    }
    if (this._phase === "arming") {
      if (!spawnCandidate) { this._phase = "idle"; this._candidateSinceMs = null; return; }
      if (this._candidateSinceMs === null) this._candidateSinceMs = now;
      else if (now - this._candidateSinceMs >= 1_000) this._startLife(now);
      return;
    }
    if (this._phase === "alive" || this._phase === "loss-pending") {
      if (playerPresent) {
        this._phase = "alive";
        this._candidateSinceMs = null;
      } else if (groundContinuity) {
        this._phase = "alive";
        this._candidateSinceMs = null;
      } else if (!this._resetSuppressedUntilEvidence) {
        this._beginSortieReset(now, "aircraft-loss");
      }
      return;
    }
    if (this._phase === "wait-next" && spawnCandidate) {
      if (this._candidateSinceMs === null) this._candidateSinceMs = now;
      else if (now - this._candidateSinceMs >= 1_000) this._startLife(now);
    } else if (this._phase === "wait-next") {
      this._candidateSinceMs = null;
    }
  }

  protected _beginSortieReset(nowMs: number, reason: SortieResetReason): void {
    if (this._resetUndo && nowMs <= this._resetUndo.expiresAtMs) return;
    const restore = this._captureSortieRestorePoint(nowMs);
    if (!restore) return;
    this._resetUndo = Object.freeze({
      reason,
      createdAtMs: nowMs,
      expiresAtMs: nowMs + RESET_UNDO_WINDOW_MS,
      restore,
    });
    this._phase = "wait-next";
    this._lifeStartedAtMs = null;
    this._resetExtension("loss");
    this._candidateSinceMs = null;
    this._noDataSinceMs = null;
    this._lifecycleEvidenceMissingSinceMs = null;
    this._resetSuppressedUntilEvidence = false;
    this._clearGroundContinuity();
    this._timerCheckpointStore?.clear();
    this._lastTimerCheckpointAtMs = 0;
    this._persistSortieRecovery(nowMs, true);
  }

  protected _undoSortieReset(nowMs: number): EditionSnapshot {
    const reset = this._resetUndo;
    if (!reset || nowMs > reset.expiresAtMs) {
      this._expireResetUndo(nowMs);
      throw new Error("重置撤销窗口已结束");
    }
    this._applySortieRestorePoint(reset.restore);
    this._resetUndo = null;
    this._resetSuppressedUntilEvidence = true;
    this._noDataSinceMs = nowMs;
    this._lifecycleEvidenceMissingSinceMs = nowMs;
    this._settingsStore.save(this._settings);
    this._persistTimerCheckpoint(nowMs, true);
    this._persistSortieRecovery(nowMs, true);
    this._revision += 1;
    this._lastSnapshot = Object.freeze({
      ...this._lastSnapshot,
      revision: this._revision,
      sampledAtMs: nowMs,
      phase: this._phase,
      timer: this._buildTimer(nowMs),
      sortieContinuity: this._buildSortieContinuity(nowMs),
      checklist: this._edition.capabilities.checklist
        ? Object.freeze({
            items: this._settings.checklistItems,
            checked: Object.freeze([...this._checklistChecked]),
          })
        : null,
    });
    return this._lastSnapshot;
  }

  protected _expireResetUndo(nowMs: number): void {
    if (!this._resetUndo || nowMs <= this._resetUndo.expiresAtMs) return;
    this._resetUndo = null;
    this._persistSortieRecovery(nowMs, true);
    if (this._lastSnapshot.sortieContinuity.resetUndo) {
      this._lastSnapshot = Object.freeze({
        ...this._lastSnapshot,
        sortieContinuity: this._buildSortieContinuity(nowMs),
      });
    }
  }

  protected _captureSortieRestorePoint(nowMs: number): SortieRestorePoint | null {
    if (
      (this._phase !== "alive" && this._phase !== "loss-pending")
      || this._lifeStartedAtMs === null
    ) return null;
    return Object.freeze({
      savedAtMs: nowMs,
      mapSignature: this._currentMapSignature || "unmatched-current-sortie",
      phase: this._phase,
      lifeStartedAtMs: this._lifeStartedAtMs,
      lifeIndex: this._lifeIndex,
      cycleSeconds: this._settings.cycleMinutes * 60,
      selectedNavigationId: this._settings.selectedNavigationId,
      navigationSelectionMode: this._navigationSelectionMode,
      ...this._captureExtension(),
      checklistChecked: Object.freeze([...this._checklistChecked]),
      resetSuppressedUntilEvidence: this._resetSuppressedUntilEvidence,
    });
  }

  protected _applySortieRestorePoint(restore: SortieRestorePoint): void {
    this._currentMapSignature = restore.mapSignature;
    this._phase = restore.phase;
    this._lifeStartedAtMs = restore.lifeStartedAtMs;
    this._lifeIndex = restore.lifeIndex;
    this._settings = { ...this._settings, selectedNavigationId: restore.selectedNavigationId };
    this._navigationSelectionMode = restore.navigationSelectionMode;
    this._restoreExtension(restore);
    this._checklistChecked = this._settings.checklistItems.map((_, index) => restore.checklistChecked[index] === true);
    this._resetSuppressedUntilEvidence = restore.resetSuppressedUntilEvidence;
    this._candidateSinceMs = null;
  }

  protected _reconcilePendingSortieResume(mapSignature: string): void {
    const restore = this._pendingSortieResume;
    if (!restore) return;
    this._pendingSortieResume = null;
    if (restore.mapSignature !== mapSignature) {
      this._sortieRecoveryStore?.clear();
      this._timerCheckpointStore?.clear();
      this._phase = "idle";
      this._lifeStartedAtMs = null;
      this._lifeIndex = 0;
      return;
    }
    this._applySortieRestorePoint(restore);
    this._persistTimerCheckpoint(this._now(), true);
  }

  protected _persistSortieRecovery(nowMs: number, force = false): void {
    const store = this._sortieRecoveryStore;
    if (!store) return;
    if (!force && nowMs - this._lastSortieRecoveryAtMs < 1_000) return;
    const resume = this._captureSortieRestorePoint(nowMs);
    const resetUndo = this._resetUndo && nowMs <= this._resetUndo.expiresAtMs ? this._resetUndo : null;
    if (!resume && !resetUndo) {
      store.clear();
      this._lastSortieRecoveryAtMs = 0;
      return;
    }
    store.save(Object.freeze({ schemaVersion: 1, resume, resetUndo }));
    this._lastSortieRecoveryAtMs = nowMs;
  }

  protected _buildSortieContinuity(nowMs: number): EditionSnapshot["sortieContinuity"] {
    if (this._resetUndo && nowMs <= this._resetUndo.expiresAtMs) {
      return Object.freeze({
        state: "reset-undo",
        graceExpiresAtMs: null,
        resetUndo: Object.freeze({ reason: this._resetUndo.reason, expiresAtMs: this._resetUndo.expiresAtMs }),
      });
    }
    if (this._noDataSinceMs !== null && (this._phase === "alive" || this._phase === "loss-pending")) {
      if (this._resetSuppressedUntilEvidence) {
        return Object.freeze({
          state: "reset-cancelled",
          graceExpiresAtMs: null,
          resetUndo: null,
        });
      }
      if (this._lifecycleEvidenceMissingSinceMs === null) {
        return Object.freeze({ state: "partial-data", graceExpiresAtMs: null, resetUndo: null });
      }
      return Object.freeze({
        state: "no-data-grace",
        graceExpiresAtMs: this._lifecycleEvidenceMissingSinceMs + NO_DATA_GRACE_MS,
        resetUndo: null,
      });
    }
    return Object.freeze({ state: "live", graceExpiresAtMs: null, resetUndo: null });
  }

  protected _startLife(now: number): void {
    this._resetExtension("life");
    this._phase = "alive";
    this._lifeStartedAtMs = now;
    this._lifeIndex += 1;
    this._candidateSinceMs = null;
    this._resetUndo = null;
    this._resetSuppressedUntilEvidence = false;
    this._clearGroundContinuity();
    this._fuel.reset();
    this._checklistChecked.fill(false);
    this._navigationSelectionMode = "auto";
    this._settings = { ...this._settings, selectedNavigationId: null };
    this._persistTimerCheckpoint(now, true);
  }

  protected _clearGroundContinuity(): void {
    this._lastPlayerFlightEvidence = null;
    this._groundContinuitySinceMs = null;
  }

  protected _persistTimerCheckpoint(nowMs: number, force = false): void {
    const store = this._timerCheckpointStore;
    if (!store || this._lifeStartedAtMs === null || (this._phase !== "alive" && this._phase !== "loss-pending")) return;
    if (!force && nowMs - this._lastTimerCheckpointAtMs < 1_000) return;
    store.save(Object.freeze({
      lifeStartedAtMs: this._lifeStartedAtMs,
      savedAtMs: nowMs,
      cycleSeconds: this._settings.cycleMinutes * 60,
      lifeIndex: this._lifeIndex,
      phase: this._phase,
    }));
    this._lastTimerCheckpointAtMs = nowMs;
  }

  protected _buildTimer(nowMs: number): EditionSnapshot["timer"] {
    if ((this._phase !== "alive" && this._phase !== "loss-pending") || this._lifeStartedAtMs === null) {
      return Object.freeze({ remainingSec: null, progress: 0, cycle: null, lifeIndex: null, cycleMinutes: this._settings.cycleMinutes });
    }
    const cycleSeconds = this._settings.cycleMinutes * 60;
    const elapsedSeconds = Math.max(0, (nowMs - this._lifeStartedAtMs) / 1_000);
    return Object.freeze({
      remainingSec: cycleSeconds - elapsedSeconds % cycleSeconds,
      progress: elapsedSeconds % cycleSeconds / cycleSeconds,
      cycle: Math.floor(elapsedSeconds / cycleSeconds) + 1,
      lifeIndex: this._lifeIndex,
      cycleMinutes: this._settings.cycleMinutes,
    });
  }

  protected _buildContinuityNavigation(current: EditionSnapshot["navigation"]): EditionSnapshot["navigation"] {
    const previous = this._lastSnapshot.navigation;
    if (!previous) return current;
    const items = previous.items.filter((item) => item.kind !== "hostile");
    const target = previous.target && previous.target.kind !== "hostile"
      ? items.find((item) => item.id === previous.target!.id) ?? null
      : null;
    return Object.freeze({
      player: null,
      mapScaleM: current?.mapScaleM ?? previous.mapScaleM,
      items: Object.freeze(items),
      target,
      selectionMode: this._navigationSelectionMode,
    });
  }

  protected _buildFuel(navigation: EditionSnapshot["navigation"], nowMs: number, live: boolean): EditionSnapshot["fuel"] {
    if (!this._edition.capabilities.fuel) return null;
    const locked = navigation?.selectionMode === "locked" && navigation.target?.kind === "airfield"
      && navigation.target.friendly ? navigation.target : null;
    const friendly = locked ?? navigation?.items.filter((item) => item.kind === "airfield" && item.friendly)
      .sort((a, b) => a.distanceKm - b.distanceKm)[0] ?? null;
    return this._fuel.view(nowMs, live, friendly, this._groundTrackEstimate?.valid === true);
  }
  protected _buildNavigation(frame: Official8111Frame, map: ParsedMap, headingDeg: number): EditionSnapshot["navigation"] {
    if (!this._edition.capabilities.zoneNavigation && !this._edition.capabilities.airfieldNavigation) return null;
    const scale = parseMapScale(frame.mapInfo);
    const player = map.player;
    if (!player) return Object.freeze({ player: null, mapScaleM: scale, items: [], target: null, selectionMode: this._navigationSelectionMode });
    const items = this._navigationObjects(map).filter(item => this._navigationAllowed(item)).map(item => {
      const { distanceKm, bearingDeg } = bearingDistance(player.x, player.y, item.x, item.y, scale);
      return this._decorateNavigation(Object.freeze({ ...item, distanceKm, bearingDeg,
        relativeDeg: normalizeAngle(bearingDeg - headingDeg), selected: item.id === this._settings.selectedNavigationId }));
    }).sort((left, right) => left.distanceKm - right.distanceKm);
    const target = this._selectNavigationTarget(items, frame);
    this._automaticNavigationTargetId = target?.id ?? null;
    this._navigationTargetUpdated(target);
    return Object.freeze({ player: Object.freeze({ x: player.x, y: player.y }), mapScaleM: scale,
      items: Object.freeze(items), target, selectionMode: this._navigationSelectionMode });
  }

  protected _selectNavigationTarget(items: readonly NavigationItem[], _frame: Official8111Frame): NavigationItem | null {
    if (this._navigationSelectionMode === "locked") return items.find(item => item.selected) ?? null;
    if (this._navigationSelectionMode !== "auto") return null;
    return items.find(item => item.id === this._automaticNavigationTargetId)
      ?? items.find(item => Math.abs(item.relativeDeg) <= 45) ?? null;
  }

  protected _navigationObjects(map: ParsedMap): ParsedMap["objects"] { return map.objects; }
  protected _navigationAllowed(item: ParsedMap["objects"][number]): boolean {
    return item.kind === "zone" && this._edition.capabilities.zoneNavigation
      || item.kind === "airfield" && this._edition.capabilities.airfieldNavigation;
  }
  protected _decorateNavigation(item: NavigationItem): NavigationItem { return item; }
  protected _navigationSelected(_item: NavigationItem): void {}
  protected _navigationTargetUpdated(_item: NavigationItem | null): void {}
  protected _parseMap(payload: Official8111Frame["mapObjects"]): ParsedMap { return parseBasicMap(payload); }
  protected _resetExtension(_reason: "map" | "hangar" | "life" | "loss"): void {}
  protected _landingElevation(_point: readonly [number, number]): number | null { return null; }
  protected _observeExtension(_frame: Official8111Frame, _map: ParsedMap, _continuity: EditionSnapshot["sortieContinuity"]): void {}
  protected _snapshotExtension(_telemetry: ParsedTelemetry, _navigation: EditionSnapshot["navigation"], _heading: number,
    _continuity: EditionSnapshot["sortieContinuity"]): Pick<EditionSnapshot, "destroyedZones" | "mapGrid" | "markedZones" | "gameChat" | "strikeSelection" | "strike"> {
    return { destroyedZones: [], mapGrid: null, markedZones: [], gameChat: [], strikeSelection: null, strike: null };
  }
  protected _extensionAlerts(_nowMs: number): string[] { return []; }
  protected _extensionCommand(_command: EditionCommand): boolean { return false; }
  protected _afterCommand(_command: EditionCommand): void {}
  protected _captureExtension(): Pick<SortieRestorePoint, "manualPoi" | "strikeTargetPoint"> { return { manualPoi: null, strikeTargetPoint: null }; }
  protected _restoreExtension(_restore: SortieRestorePoint): void {}
}

export function isStrikeTargetMode(value: unknown): value is StrikeTargetMode {
  return value === "auto" || value === "zone" || value === "airfield-module" || value === "poi" || value === "hostile";
}

export function isStrikeAirfieldModule(value: unknown): value is StrikeAirfieldModule {
  return value === "airfield" || value === "storage" || value === "parking" || value === "dwelling";
}

function normalizeTimerCheckpoint(
  value: unknown,
  expectedCycleSeconds: number,
  nowMs: number,
): TimerCheckpoint | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const checkpoint = value as Partial<TimerCheckpoint>;
  if (
    !Number.isFinite(checkpoint.lifeStartedAtMs)
    || !Number.isFinite(checkpoint.savedAtMs)
    || checkpoint.cycleSeconds !== expectedCycleSeconds
    || !Number.isInteger(checkpoint.lifeIndex)
    || checkpoint.lifeIndex! < 1
    || (checkpoint.phase !== "alive" && checkpoint.phase !== "loss-pending")
  ) return null;
  const lifeStartedAtMs = checkpoint.lifeStartedAtMs!;
  const savedAtMs = checkpoint.savedAtMs!;
  if (
    lifeStartedAtMs > savedAtMs
    || savedAtMs > nowMs + 5 * 60_000
    || nowMs - savedAtMs > 12 * 60 * 60_000
  ) return null;
  return Object.freeze({
    lifeStartedAtMs,
    savedAtMs,
    cycleSeconds: expectedCycleSeconds,
    lifeIndex: checkpoint.lifeIndex!,
    phase: checkpoint.phase,
  });
}

function normalizeSettings(value: Partial<RuntimeSettings> | null): RuntimeSettings {
  const cycleMinutes = Number.isInteger(value?.cycleMinutes) && value!.cycleMinutes! >= 1 && value!.cycleMinutes! <= 180
    ? value!.cycleMinutes!
    : 15;
  return Object.freeze({
    cycleMinutes,
    checklistItems: normalizeChecklist(value?.checklistItems ?? DEFAULT_CHECKLIST),
    selectedNavigationId: typeof value?.selectedNavigationId === "string" ? value.selectedNavigationId : null,
    selectedWeaponId: typeof value?.selectedWeaponId === "string" ? value.selectedWeaponId : "",
    targetAltitudeM: typeof value?.targetAltitudeM === "number" && Number.isFinite(value.targetAltitudeM)
      ? value.targetAltitudeM
      : 0,
    strikeTargetMode: isStrikeTargetMode(value?.strikeTargetMode) ? value.strikeTargetMode : "auto",
    strikeAirfieldModule: isStrikeAirfieldModule(value?.strikeAirfieldModule)
      ? value.strikeAirfieldModule
      : "airfield",
  });
}

function normalizeChecklist(raw: readonly string[]): readonly string[] {
  const items = raw.map((item) => String(item).trim()).filter(Boolean).slice(0, 8);
  return Object.freeze(items.length ? items : [...DEFAULT_CHECKLIST]);
}

function emptySnapshot(edition: EditionPolicy, settings: RuntimeSettings): EditionSnapshot {
  return Object.freeze({
    edition,
    revision: 0,
    sampledAtMs: 0,
    mapObjectsSampledAtMs: 0,
    connected: false,
    phase: "idle",
    sortieContinuity: Object.freeze({ state: "live", graceExpiresAtMs: null, resetUndo: null }),
    timer: Object.freeze({ remainingSec: null, progress: 0, cycle: null, lifeIndex: null, cycleMinutes: settings.cycleMinutes }),
    flight: Object.freeze({
      aircraft: "", altitudeM: 0, iasKmh: 0, tasKmh: 0, verticalSpeedMps: 0,
      headingDeg: 0, mach: null, gearPercent: 0, onGround: true,
      overspeed: Object.freeze({ level: "none", ratio: 0, iasLimitKmh: 0, machLimit: 0, matched: false }),
    }),
    navigation: null,
    destroyedZones: Object.freeze([]),
    mapGrid: null,
    markedZones: Object.freeze([]),
    gameChat: Object.freeze([]),
    fuel: null,
    checklist: null,
    strikeSelection: edition.capabilities.strikePrediction
      ? Object.freeze({
          targetMode: settings.strikeTargetMode,
          airfieldModule: settings.strikeAirfieldModule,
          target: null,
        })
      : null,
    strike: null,
    alerts: [],
  });
}

function hasGroundContinuity(
  current: ParsedTelemetry,
  previous: PlayerFlightEvidence | null,
  nowMs: number,
): boolean {
  if (!current.stateValid || !current.onGround || !previous) return false;
  if (nowMs - previous.sampledAtMs > LANDING_EVIDENCE_MAX_AGE_MS) return false;
  if (previous.onGround) return true;
  return previous.gearPercent >= LOW_ENERGY_APPROACH_MIN_GEAR_PERCENT
    && previous.iasKmh <= LOW_ENERGY_APPROACH_MAX_IAS_KMH
    && Math.abs(previous.verticalSpeedMps) <= LOW_ENERGY_APPROACH_MAX_VERTICAL_SPEED_MPS;
}

function parseTelemetry(frame: Official8111Frame): ParsedTelemetry {
  const indicators = frame.indicators ?? {};
  const state = frame.state ?? {};
  const aircraft = textField(indicators, ["type", "unit", "aircraft", "aircraft_type", "vehicle", "model", "name"]);
  const iasKmh = numericField(state, ["IAS, km/h", "IAS", "ias"], 0);
  const verticalSpeedMps = numericField(state, ["Vy, m/s", "Vy", "vy"], 0);
  const fuelKg = numericField(state, ["Mfuel, kg", "Mfuel", "fuel"], 0);
  const altitudeM = numericField(state, ["H, m", "H", "altitude"], 0);
  const stateValid = ["IAS, km/h", "Vy, m/s", "Mfuel, kg", "H, m"].every((key) => finiteValue(state[key]) !== null);
  const indicatorsValid = indicators.valid === true && Boolean(aircraft);
  const heading = optionalNumericField(indicators, ["compass1", "compass", "compass1, deg", "compass, deg"]);
  const gearPercent = numericField(state, ["gear, %", "gear"], 0);
  return {
    aircraft,
    indicatorsValid,
    stateValid,
    iasKmh,
    tasKmh: numericField(state, ["TAS, km/h", "TAS", "tas"], 0),
    tasObserved: numericField(state, ["TAS, km/h", "TAS", "tas"], 0) >= 36,
    verticalSpeedMps,
    altitudeM,
    fuelKg,
    fuel0Kg: numericField(state, ["Mfuel0, kg", "Mfuel0", "fuel0"], 0),
    mach: optionalNumericField(state, ["M", "Mach", "mach", "mach_number"]),
    gearPercent,
    aoaDeg: optionalNumericField(state, ["AoA, deg", "AoA", "aoa"]),
    headingDeg: heading === null ? null : normalizeHeading(heading),
    entityLike: indicatorsValid && stateValid && (fuelKg > 0.1 || Math.abs(iasKmh) > 0.1 || Math.abs(verticalSpeedMps) > 0.1),
    onGround: iasKmh < 40 && Math.abs(verticalSpeedMps) < 2,
  };
}

export function parseBasicMap(payload: Official8111Frame["mapObjects"]): ParsedMap {
  const objects = extractObjects(payload);
  const playerRaw = selectPlayerObject(objects);
  const player = playerRaw ? position(playerRaw) : null;
  const parsed: ParsedMap["objects"] = [];
  let zoneIndex = 1;
  let airfieldIndex = 1;
  for (const object of objects) {
    if (object === playerRaw) continue;
    const officialIcon = textField(object, ["icon"]);
    if (isAirfield(object)) {
      const resolved = runwayCenter(object) ?? position(object);
      if (!resolved || resolved.x < 0 || resolved.x > 1 || resolved.y < 0 || resolved.y > 1) continue;
      const number = airfieldIndex++;
      parsed.push({ id: `airfield_${number}`, kind: "airfield", label: `机场 ${number}`, x: resolved.x, y: resolved.y, friendly: isFriendly(object), hostile: isHostile(object), ...(officialIcon ? { officialIcon } : {}) });
      const endpoints = runwayEndpoints(object);
      if (endpoints) {
        const item = parsed.at(-1)!;
        item.runwayStart = endpoints.start;
        item.runwayEnd = endpoints.end;
      }
      continue;
    }
    const point = position(object);
    if (!point || point.x < 0 || point.x > 1 || point.y < 0 || point.y > 1) continue;
    if (isZone(object)) {
      parsed.push({ id: `zone_${point.x.toFixed(4)}_${point.y.toFixed(4)}`, kind: "zone", label: `战区 ${zoneIndex++}`, x: point.x, y: point.y, friendly: false, hostile: true, ...(officialIcon ? { officialIcon } : {}) });
    }
  }
  return {
    player: player ? { ...player, dx: numericField(playerRaw!, ["dx", "DX", "vel_x", "vx"], 0), dy: numericField(playerRaw!, ["dy", "DY", "vel_y", "vy"], 0) } : null,
    objects: parsed,
    objectCount: objects.length,
  };
}

export function extractObjects(payload: Official8111Frame["mapObjects"]): Record<string, unknown>[] {
  if (Array.isArray(payload)) return payload.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object" && !Array.isArray(item)));
  if (!payload || typeof payload !== "object") return [];
  const record = payload as Readonly<Record<string, unknown>>;
  for (const key of ["objects", "map_objects", "items", "data"]) {
    const value = record[key];
    if (Array.isArray(value)) return value.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object" && !Array.isArray(item)));
  }
  return [];
}

export function selectPlayerObject(objects: Record<string, unknown>[]): Record<string, unknown> | null {
  const ranked = objects.map((object, index) => ({ object, index, rank: playerRank(object) })).filter((item) => item.rank > 0);
  for (const rank of [3, 2]) {
    const found = ranked.find((item) => item.rank === rank);
    if (found) return found.object;
  }
  const fallback = ranked.filter((item) => item.rank === 1);
  return fallback.length === 1 ? fallback[0]!.object : null;
}

function playerRank(object: Record<string, unknown>): number {
  if (["is_player", "player", "is_self", "self"].some((key) => object[key] === true)) return 3;
  const type = lowerText(object.type);
  if (type === "player" || type === "player_aircraft") return 3;
  const icon = lowerText(object.icon);
  const name = lowerText(object.name ?? object.label);
  const playerLike = isAircraft(object) && (icon === "player" || name === "player" || icon.includes("player"));
  return playerLike ? (isYellowOrGold(object) ? 2 : 1) : 0;
}

export function isAircraft(object: Record<string, unknown>): boolean {
  const type = lowerText(object.type);
  const icon = lowerText(object.icon);
  return ["aircraft", "plane", "player", "player_aircraft"].includes(type)
    || ["fighter", "assault", "bomber", "helicopter"].includes(icon);
}

export function isAirfield(object: Record<string, unknown>): boolean {
  return ["airfield", "airport", "runway"].includes(lowerText(object.type))
    || ["airfield", "airport", "runway"].includes(lowerText(object.icon));
}

export function isZone(object: Record<string, unknown>): boolean {
  const type = lowerText(object.type);
  const icon = lowerText(object.icon);
  return ["bombing_point", "bombingpoint", "bombing point", "bomb_target", "bomb_target_point"].includes(type)
    || icon.includes("bombing") || icon.includes("bomb_target");
}

export function isMapFeature(object: Record<string, unknown>): boolean {
  const type = lowerText(object.type);
  const icon = lowerText(object.icon);
  return isAirfield(object) || isZone(object) || type === "point_of_interest"
    || ["capture_zone", "defending_point", "spawn_point", "waypoint"].some((token) => type.includes(token) || icon.includes(token));
}

export function isFriendly(object: Record<string, unknown>): boolean {
  const side = lowerText(object.side ?? object.team ?? object.army);
  if (["friendly", "ally", "allied", "blue", "team_a", "1"].includes(side)) return true;
  if (["enemy", "hostile", "red", "team_b", "2"].includes(side)) return false;
  const color = lowerText(object.color);
  if (color.includes("blue") || color === "#0000ff" || color === "0x0000ff") return true;
  const channels = officialColorChannels(object);
  return channels !== null && channels[2] - channels[0] >= 48 && channels[2] - channels[1] >= 48;
}

export function isHostile(object: Record<string, unknown>): boolean {
  const side = lowerText(object.side ?? object.team ?? object.army);
  if (["enemy", "hostile", "red", "team_b", "2"].includes(side)) return true;
  if (["friendly", "ally", "allied", "blue", "team_a", "1"].includes(side)) return false;
  if (lowerText(object.color).includes("red")) return true;
  const channels = officialColorChannels(object);
  return channels !== null && channels[0] - channels[1] >= 48 && channels[0] - channels[2] >= 48;
}

function officialColorChannels(object: Record<string, unknown>): readonly [number, number, number] | null {
  const vector = object["color[]"];
  if (
    Array.isArray(vector)
    && vector.length >= 3
    && vector.slice(0, 3).every((value) => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 255)
  ) return [vector[0] as number, vector[1] as number, vector[2] as number];
  const color = lowerText(object.color).replace(/^0x/, "#");
  const match = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(color);
  return match
    ? [Number.parseInt(match[1]!, 16), Number.parseInt(match[2]!, 16), Number.parseInt(match[3]!, 16)]
    : null;
}

function isYellowOrGold(object: Record<string, unknown>): boolean {
  const color = lowerText(object.color);
  return color.includes("yellow") || color.includes("gold") || color.includes("amber");
}

export function position(object: Record<string, unknown>): { x: number; y: number } | null {
  const x = optionalNumericField(object, ["x", "X", "pos_x", "position_x"]);
  const y = optionalNumericField(object, ["y", "Y", "pos_y", "position_y"]);
  return x === null || y === null ? null : { x, y };
}

function runwayCenter(object: Record<string, unknown>): { x: number; y: number } | null {
  const sx = optionalNumericField(object, ["sx", "start_x", "runway_start_x"]);
  const sy = optionalNumericField(object, ["sy", "start_y", "runway_start_y"]);
  const ex = optionalNumericField(object, ["ex", "end_x", "runway_end_x"]);
  const ey = optionalNumericField(object, ["ey", "end_y", "runway_end_y"]);
  return sx === null || sy === null || ex === null || ey === null ? null : { x: (sx + ex) / 2, y: (sy + ey) / 2 };
}

function runwayEndpoints(object: Record<string, unknown>): {
  start: readonly [number, number];
  end: readonly [number, number];
} | null {
  const sx = optionalNumericField(object, ["sx", "start_x", "runway_start_x"]);
  const sy = optionalNumericField(object, ["sy", "start_y", "runway_start_y"]);
  const ex = optionalNumericField(object, ["ex", "end_x", "runway_end_x"]);
  const ey = optionalNumericField(object, ["ey", "end_y", "runway_end_y"]);
  return sx === null || sy === null || ex === null || ey === null
    ? null
    : { start: Object.freeze([sx, sy]), end: Object.freeze([ex, ey]) };
}

function parseMapScale(mapInfo: Readonly<Record<string, unknown>> | null): readonly [number, number] | null {
  const normalized = normalizeOfficialMapInfo(mapInfo);
  if (!normalized) return null;
  const x = normalized.maximum[0] - normalized.minimum[0];
  const y = normalized.maximum[1] - normalized.minimum[1];
  return x > 1e-6 && y > 1e-6 ? Object.freeze([x, y]) : null;
}

export function bearingDistance(px: number, py: number, tx: number, ty: number, scale: readonly [number, number] | null): { distanceKm: number; bearingDeg: number } {
  const dx = tx - px;
  const dy = ty - py;
  const dxM = scale ? dx * scale[0] : dx * 100_000;
  const dyM = scale ? dy * scale[1] : dy * 100_000;
  return { distanceKm: Math.hypot(dxM, dyM) / 1_000, bearingDeg: normalizeHeading(Math.atan2(dxM, -dyM) * 180 / Math.PI) };
}

function mapHeading(player: ParsedMap["player"]): number {
  if (!player || Math.hypot(player.dx, player.dy) <= 1e-9) return 0;
  return normalizeHeading(Math.atan2(player.dx, -player.dy) * 180 / Math.PI);
}

function evaluateOverspeed(aircraft: string, iasKmh: number, mach: number | null, catalog: AircraftParameters | null, sweep: number | null, flapsPercent: number | null): EditionSnapshot["flight"]["overspeed"] {
  const limit = catalog?.speed(aircraft, sweep);
  let iasLimit = finiteValue(limit?.ias) ?? 0;
  let iasLimitSource: "airframe" | "flaps" | null = iasLimit > 0 ? "airframe" : null;
  const flapLimit = landingFlapReference(catalog?.landing(aircraft), flapsPercent, iasKmh, "unknown").limitIasKmh;
  if (flapLimit !== null && (iasLimit <= 0 || flapLimit < iasLimit)) {
    iasLimit = flapLimit;
    iasLimitSource = "flaps";
  }
  const machLimit = finiteValue(limit?.mach) ?? 0;
  const ratio = iasLimit > 0 ? Math.max(0, iasKmh / iasLimit) : 0;
  const machMargin = mach !== null && machLimit > 0 ? machLimit - mach : Number.POSITIVE_INFINITY;
  let level: "none" | "caution" | "warning" | "critical" = "none";
  if (ratio >= 0.992 || machMargin <= 0.02) level = "critical";
  else if (ratio >= 0.97 || machMargin <= 0.04) level = "warning";
  else if (ratio >= 0.94 || machMargin <= 0.06) level = "caution";
  return Object.freeze({ level, ratio, iasLimitKmh: iasLimit, iasLimitSource, machLimit,
    matched: Boolean(limit) || flapLimit !== null, estimated: limit?.estimated ?? false });
}

function numericField(record: Readonly<Record<string, unknown>>, keys: readonly string[], fallback: number): number {
  return optionalNumericField(record, keys) ?? fallback;
}

export function optionalNumericField(record: Readonly<Record<string, unknown>>, keys: readonly string[]): number | null {
  for (const key of keys) {
    const value = finiteValue(record[key]);
    if (value !== null) return value;
  }
  return null;
}

function finiteValue(raw: unknown): number | null {
  if (raw && typeof raw === "object" && !Array.isArray(raw)) raw = (raw as Record<string, unknown>).value;
  else if (Array.isArray(raw)) raw = raw[0];
  const value = typeof raw === "number" ? raw : typeof raw === "string" && raw.trim() ? Number(raw) : Number.NaN;
  return Number.isFinite(value) ? value : null;
}

export function textField(record: Readonly<Record<string, unknown>>, keys: readonly string[]): string {
  for (const key of keys) {
    const value = lowerableText(record[key]);
    if (value) return value;
  }
  return "";
}

export function lowerText(value: unknown): string { return lowerableText(value).toLowerCase(); }

function lowerableText(raw: unknown): string {
  if (raw && typeof raw === "object" && !Array.isArray(raw)) raw = (raw as Record<string, unknown>).value;
  else if (Array.isArray(raw)) raw = raw[0];
  return String(raw ?? "").trim();
}

function normalizeHeading(value: number): number { return (value % 360 + 360) % 360; }
export function normalizeAngle(value: number): number { return ((value + 180) % 360 + 360) % 360 - 180; }
