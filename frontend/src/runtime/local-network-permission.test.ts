import { describe, expect, it, vi } from "vitest";
import { queryLocalNetworkPermission } from "./local-network-permission";

describe("local network permission", () => {
  it("queries the split loopback permission used by desktop Bridge", async () => {
    const query = vi.fn(async () => ({ state: "denied" as PermissionState }) as PermissionStatus);
    await expect(queryLocalNetworkPermission("loopback", query)).resolves.toBe("denied");
    expect(query).toHaveBeenCalledWith({ name: "loopback-network" });
  });

  it("falls back to the legacy combined permission on older Edge builds", async () => {
    const query = vi.fn(async (descriptor: PermissionDescriptor) => {
      if (String(descriptor.name) === "loopback-network") throw new TypeError("unsupported permission name");
      return { state: "granted" as PermissionState } as PermissionStatus;
    });
    await expect(queryLocalNetworkPermission("loopback", query)).resolves.toBe("granted");
    expect(query.mock.calls.map(([descriptor]) => descriptor.name)).toEqual(["loopback-network", "local-network-access"]);
  });

  it("does not guess when the browser exposes no queryable permission", async () => {
    await expect(queryLocalNetworkPermission("loopback", undefined)).resolves.toBe("unsupported");
  });
});
