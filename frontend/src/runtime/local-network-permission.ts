export type LocalNetworkPermissionTarget = "loopback" | "local";
export type LocalNetworkPermissionState = PermissionState | "unsupported";

type PermissionQuery = (descriptor: PermissionDescriptor) => Promise<PermissionStatus>;

export async function queryLocalNetworkPermission(
  target: LocalNetworkPermissionTarget,
  query: PermissionQuery | undefined = globalThis.navigator?.permissions?.query?.bind(globalThis.navigator.permissions),
): Promise<LocalNetworkPermissionState> {
  if (!query) return "unsupported";
  const primary = target === "loopback" ? "loopback-network" : "local-network";
  for (const name of [primary, "local-network-access"] as const) {
    try {
      const status = await query({ name: name as PermissionName });
      if (status.state === "granted" || status.state === "denied" || status.state === "prompt") return status.state;
    } catch {
      continue;
    }
  }
  return "unsupported";
}
