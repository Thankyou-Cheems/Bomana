export interface BridgeRelease {
  readonly schemaVersion: 1;
  readonly bridgeVersion: string;
  readonly bridgeSha256: string;
}

export type BridgeVersionState = "current" | "outdated" | "newer" | "unknown";

type Fetcher = typeof fetch;

export async function fetchBridgeRelease(
  url: URL,
  fetcher: Fetcher = fetch,
): Promise<BridgeRelease> {
  const response = await fetcher(url, {
    method: "GET",
    mode: "same-origin",
    cache: "no-store",
    credentials: "omit",
    redirect: "error",
    referrerPolicy: "no-referrer",
  });
  if (!response.ok) throw new Error(`Bridge release HTTP ${response.status}`);
  const raw = await response.text();
  if (raw.length < 32 || raw.length > 4_096) throw new Error("Bridge release document size is invalid");
  const value = JSON.parse(raw) as Record<string, unknown>;
  if (
    value.schema_version !== 1
    || !strictVersion(value.bridge_version)
    || typeof value.bridge_sha256 !== "string"
    || !/^[0-9a-f]{64}$/.test(value.bridge_sha256)
  ) throw new Error("Bridge release document is invalid");
  return Object.freeze({
    schemaVersion: 1,
    bridgeVersion: value.bridge_version,
    bridgeSha256: value.bridge_sha256,
  });
}

export function bridgeVersionState(localVersion: string, latestVersion: string): BridgeVersionState {
  const local = versionTuple(localVersion);
  const latest = versionTuple(latestVersion);
  if (!local || !latest) return "unknown";
  for (let index = 0; index < local.length; index += 1) {
    if (local[index]! < latest[index]!) return "outdated";
    if (local[index]! > latest[index]!) return "newer";
  }
  return "current";
}

function strictVersion(value: unknown): value is string {
  return typeof value === "string" && /^(0|[1-9]\d*)[.](0|[1-9]\d*)[.](0|[1-9]\d*)$/.test(value);
}

function versionTuple(value: string): readonly [number, number, number] | null {
  if (!strictVersion(value)) return null;
  const parts = value.split(".").map(Number);
  return [parts[0]!, parts[1]!, parts[2]!] as const;
}
