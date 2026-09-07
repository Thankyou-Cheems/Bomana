import { createPublicKey, verify } from "node:crypto";
import { describe, expect, it } from "vitest";
import { downloadEnhancedDesktop } from "./desktop-download";
import { sha256Digest } from "../runtime/crypto-compat";

const base = new URL("https://pay.ruikang.wang");
const bytes = new TextEncoder().encode("a private desktop package");
const version = "0.1.0-preview.1";
const resource = `desktop/${version}/BomanaEnhanced-windows-amd64.zip`;
const url = new URL(`/subscriber-artifacts/${resource}`, base);
const hex = (v: Uint8Array): string => Array.from(v, x => x.toString(16).padStart(2, "0")).join("");

describe("Launcher Enhanced Desktop download", () => {
  it("requests eligibility online, signs with an ephemeral key and checks the private bytes", async () => {
    let key = "";
    const paths: string[] = [];
    const result = await downloadEnhancedDesktop(base, "account-token", async (input, init) => {
      const path = new URL(String(input)); paths.push(path.pathname);
      if (paths.length === 1) {
        expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer account-token");
        key = JSON.parse(String(init?.body)).publicKeySpki;
        return Response.json({ schemaVersion: 1, version, bytes: bytes.length, sha256: hex(await sha256Digest(bytes)), resource, downloadUrl: url.href, token: "private.grant.token", expiresAt: new Date(Date.now() + 300_000).toISOString() });
      }
      const h = new Headers(init?.headers);
      expect(h.get("Authorization")).toBe("Bearer private.grant.token");
      expect(init?.redirect).toBe("error");
      const canonical = `GET\n${url.pathname}\n${h.get("X-Device-Timestamp")}\n${hex(await sha256Digest(new Uint8Array()))}`;
      expect(verify(null, Buffer.from(canonical), createPublicKey({ key: Buffer.from(key, "base64url"), format: "der", type: "spki" }), Buffer.from(h.get("X-Device-Signature")!, "base64url"))).toBe(true);
      return new Response(bytes);
    });
    expect(paths).toEqual(["/api/bomana/desktop/download", url.pathname]);
    expect(result.filename).toBe(`BomanaEnhanced-${version}-windows-amd64.zip`);
    expect(await result.blob.text()).toBe("a private desktop package");
  });

  it.each(["ineligible", "unpublished", "offsite", "wrong-resource", "digest", "too-large", "expired"])("does not download unsafe or unavailable data: %s", async failure => {
    let calls = 0;
    await expect(downloadEnhancedDesktop(base, "account-token", async () => {
      calls++;
      if (calls === 1) {
        if (failure === "ineligible" || failure === "unpublished") return new Response("", { status: failure === "ineligible" ? 403 : 503 });
        return Response.json({ schemaVersion: 1, version, bytes: failure === "too-large" ? bytes.length - 1 : bytes.length,
          sha256: failure === "digest" ? "0".repeat(64) : hex(await sha256Digest(bytes)),
          resource: failure === "wrong-resource" ? "terrain/private.json" : resource,
          downloadUrl: failure === "offsite" ? "https://outside.example/private.zip" : url.href,
          token: "private.grant.token", expiresAt: new Date(Date.now() + (failure === "expired" ? -1000 : 300_000)).toISOString() });
      }
      return new Response(bytes);
    })).rejects.toThrow();
    expect(calls).toBe(["digest", "too-large"].includes(failure) ? 2 : 1);
  });
});
