export interface AppWebRelease {
  readonly schemaVersion: 1;
  readonly appWebVersion: string;
  readonly sourceCommit: string;
}

type Fetcher = typeof fetch;

export async function fetchAppWebRelease(
  url: URL,
  fetcher: Fetcher = fetch,
): Promise<AppWebRelease> {
  const response = await fetcher(url, {
    method: "GET",
    mode: "same-origin",
    cache: "no-store",
    credentials: "omit",
    redirect: "error",
    referrerPolicy: "no-referrer",
  });
  if (!response.ok) throw new Error(`App Web release HTTP ${response.status}`);
  const raw = await response.text();
  if (raw.length < 32 || raw.length > 4_096) throw new Error("App Web release document size is invalid");
  const value = JSON.parse(raw) as Record<string, unknown>;
  if (
    value.schema_version !== 1
    || !strictVersion(value.app_web_version)
    || typeof value.source_commit !== "string"
    || !/^[0-9a-f]{40}$/.test(value.source_commit)
  ) throw new Error("App Web release document is invalid");
  return Object.freeze({
    schemaVersion: 1,
    appWebVersion: value.app_web_version,
    sourceCommit: value.source_commit,
  });
}

function strictVersion(value: unknown): value is string {
  return typeof value === "string" && /^(0|[1-9]\d*)[.](0|[1-9]\d*)[.](0|[1-9]\d*)$/.test(value);
}
