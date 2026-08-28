import { describe, expect, it, vi } from "vitest";
import {
  acceptsAuthorizationCompletion,
  authorizationVerificationURL,
  beginAuthorizationAttempt,
  openAuthorizationPopup,
} from "./launcher-auth-popup";

describe("Launcher popup authorization", () => {
  it("opens a named popup synchronously before the device-code request completes", () => {
    const popup = { location: { replace: vi.fn() }, close: vi.fn(), closed: false };
    const open = vi.fn(() => popup);
    expect(openAuthorizationPopup(open)).toBe(popup);
    expect(open).toHaveBeenCalledWith(
      "about:blank",
      "bomana-cheemspay-auth",
      expect.stringContaining("popup=yes"),
    );
  });

  it("marks only the trusted CheemsPay verification URL as a Launcher popup", () => {
    expect(authorizationVerificationURL(
      "https://pay.ruikang.wang/device?user_code=ABCD2345",
      "https://pay.ruikang.wang",
      "popup",
    ).href).toBe("https://pay.ruikang.wang/device?user_code=ABCD2345&launcher=bomana");
    expect(authorizationVerificationURL(
      "https://pay.ruikang.wang/device?user_code=ABCD2345",
      "https://pay.ruikang.wang",
      "redirect",
    ).href).toBe("https://pay.ruikang.wang/device?user_code=ABCD2345&launcher=bomana&return_mode=redirect");
    expect(() => authorizationVerificationURL(
      "https://evil.example/device?user_code=ABCD2345",
      "https://pay.ruikang.wang",
      "redirect",
    )).toThrow("CheemsPay");
  });

  it("accepts completion only from the exact popup, origin, and device code", () => {
    const popup = {};
    const message = { type: "cheemspay:device-authorization-complete", userCode: "ABCD2345" };
    expect(acceptsAuthorizationCompletion({ origin: "https://pay.ruikang.wang", source: popup, data: message }, popup, "https://pay.ruikang.wang", "ABCD2345")).toBe(true);
    expect(acceptsAuthorizationCompletion({ origin: "https://evil.example", source: popup, data: message }, popup, "https://pay.ruikang.wang", "ABCD2345")).toBe(false);
    expect(acceptsAuthorizationCompletion({ origin: "https://pay.ruikang.wang", source: {}, data: message }, popup, "https://pay.ruikang.wang", "ABCD2345")).toBe(false);
  });

  it("detects a blocked popup and returns the pending access for in-page recovery", async () => {
    const begin = vi.fn(async () => ({
      state: "pending",
      userCode: "ABCD2345",
      verificationURL: "https://pay.ruikang.wang/device?user_code=ABCD2345",
    }));
    const open = vi.fn(() => null);
    const attempt = await beginAuthorizationAttempt(begin, open, "https://pay.ruikang.wang");
    expect(open.mock.invocationCallOrder[0]).toBeLessThan(begin.mock.invocationCallOrder[0]!);
    expect(attempt).toMatchObject({ blocked: true, popup: null, access: { state: "pending", userCode: "ABCD2345" } });
  });

  it("closes the placeholder popup when device-code creation fails", async () => {
    const popup = { location: { replace: vi.fn() }, close: vi.fn(), closed: false };
    await expect(beginAuthorizationAttempt(
      async () => { throw new Error("offline"); },
      () => popup,
      "https://pay.ruikang.wang",
    )).rejects.toThrow("offline");
    expect(popup.close).toHaveBeenCalledOnce();
  });
});
