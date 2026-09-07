import { AircraftParameters } from "./aircraft-parameters";
import { PUBLIC_OFFLINE_ROOT, PUBLIC_OFFLINE_URLS } from "../generated/public-offline-assets";
import { openVerifiedOfflineCatalog } from "./offline-root";
import { openSessionAssetStore, type PersistentAssetStore } from "./persistent-asset-store";

let publicCatalogPromise: ReturnType<typeof openVerifiedOfflineCatalog> | null = null;
function publicCatalog(): ReturnType<typeof openVerifiedOfflineCatalog> {
  publicCatalogPromise ??= openVerifiedOfflineCatalog(PUBLIC_OFFLINE_ROOT, PUBLIC_OFFLINE_URLS, { expectedScope: "public" });
  return publicCatalogPromise;
}

export interface StrikeRuntimeResources {
  readonly encyclopedia: Readonly<Record<string, unknown>>;
  readonly weapons: Readonly<Record<string, unknown>>;
  readonly aircraftWeapons: Readonly<Record<string, unknown>>;
  readonly splash: Readonly<Record<string, unknown>>;
}

export async function loadAircraftParameters(store?: PersistentAssetStore): Promise<AircraftParameters> {
  return AircraftParameters.parse(await loadJson("aircraft-parameters", 2_000_000, store));
}

export async function loadStrikeResources(aircraft: AircraftParameters, store?: PersistentAssetStore): Promise<StrikeRuntimeResources> {
  const [encyclopedia, weapons, splash] = await Promise.all([
    loadJson("strike-encyclopedia", 64_000, store),
    loadJson("strike-weapon-damage", 1_000_000, store),
    loadJson("bombing-zone-splash", 64_000, store),
  ]);
  return {
    encyclopedia: objectPayload(encyclopedia, "encyclopedia"),
    weapons: objectPayload(weapons, "weapon damage"),
    aircraftWeapons: aircraft.strikeCatalog(),
    splash: objectPayload(splash, "splash model"),
  };
}

async function loadJson(
  id: string,
  maxBytes: number,
  providedStore?: PersistentAssetStore,
): Promise<unknown> {
  const store = providedStore ?? await openSessionAssetStore();
  const bytes = await store.load((await publicCatalog()).asset(id));
  if (bytes.byteLength > maxBytes) throw new Error("runtime asset exceeds its size limit");
  const text = new TextDecoder().decode(bytes);
  return JSON.parse(text) as unknown;
}

function objectPayload(value: unknown, label: string): Readonly<Record<string, unknown>> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} is invalid`);
  }
  return value as Readonly<Record<string, unknown>>;
}
