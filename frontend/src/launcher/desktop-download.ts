import { sha256Digest } from "../runtime/crypto-compat";

/** A download-only key is never persisted or registered as a licensed device. */
export async function downloadEnhancedDesktop(
  base: URL, accessToken: string, fetcher: typeof fetch = fetch,
  progress: (fraction: number) => void = () => {},
): Promise<{ readonly blob: Blob; readonly filename: string }> {
  if (!accessToken) throw new Error("请先登录 CheemsPay 并验证 Enhanced 订阅");
  const [ed25519, hashes] = await Promise.all([import("@noble/ed25519"), import("@noble/hashes/sha2.js")]);
  ed25519.hashes.sha512 = hashes.sha512;
  const secret = crypto.getRandomValues(new Uint8Array(32));
  try {
    const publicKey = ed25519.getPublicKey(secret);
    const spki = new Uint8Array(44);
    spki.set([0x30, 0x2a, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x03, 0x21, 0x00]);
    spki.set(publicKey, 12);
    const grantResponse = await fetcher(new URL("/api/bomana/desktop/download", base), {
      method: "POST", credentials: "omit", cache: "no-store", redirect: "error", referrerPolicy: "no-referrer",
      signal: AbortSignal.timeout(15_000), headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({ publicKeySpki: base64url(spki) }),
    });
    if (!grantResponse.ok) {
      if (grantResponse.status === 401 || grantResponse.status === 403) throw new Error("需要有效的 Enhanced 订阅，请重新验证账户");
      if (grantResponse.status === 503 || grantResponse.status === 404) throw new Error("Enhanced Desktop 尚未开放下载");
      throw new Error(`下载授权暂不可用（HTTP ${grantResponse.status}）`);
    }
    const grant = await grantResponse.json() as Record<string, unknown>;
    const version = typeof grant.version === "string" ? grant.version : "";
    const resource = `desktop/${version}/BomanaEnhanced-windows-amd64.zip`;
    const url = new URL(String(grant.downloadUrl));
    const size = Number(grant.bytes);
    const now = Date.now();
    const expiresAt = Date.parse(String(grant.expiresAt));
    // Five-minute grants can appear longer when the issuer clock is ahead.
    // Allow one minute of clock skew; the gateway still enforces signed expiry.
    const maxRemainingMs = 5 * 60_000 + 60_000;
    if (grant.schemaVersion !== 1 || !/^\d+\.\d+\.\d+(?:-[a-z0-9.]+)?$/.test(version)
      || grant.resource !== resource || url.origin !== base.origin || url.pathname !== `/subscriber-artifacts/${resource}`
      || url.username || url.password || url.search || url.hash
      || !Number.isInteger(size) || size < 1 || size > 128 * 1024 * 1024
      || typeof grant.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(grant.sha256)
      || typeof grant.token !== "string" || !/^[A-Za-z0-9._-]{1,8192}$/.test(grant.token)
      || !Number.isFinite(expiresAt) || expiresAt <= now || expiresAt - now > maxRemainingMs) throw new Error("私有下载响应无效");
    const timestamp = new Date(now).toISOString();
    const canonical = `GET\n${url.pathname}\n${timestamp}\n${hex(await sha256Digest(new Uint8Array()))}`;
    const signature = base64url(ed25519.sign(new TextEncoder().encode(canonical), secret));
    const response = await fetcher(url, {
      method: "GET", credentials: "omit", cache: "no-store", redirect: "error", referrerPolicy: "no-referrer",
      signal: AbortSignal.timeout(180_000), headers: {
        Authorization: `Bearer ${grant.token}`, "X-Device-Timestamp": timestamp, "X-Device-Signature": signature,
      },
    });
    if (!response.ok || !response.body) throw new Error(`安装包下载失败（HTTP ${response.status}），可重新领取下载许可`);
    const chunks: Uint8Array<ArrayBuffer>[] = [];
    const reader = response.body.getReader();
    let received = 0;
    try {
      for (;;) {
        const chunk = await reader.read();
        if (chunk.done) break;
        received += chunk.value.byteLength;
        if (received > size) throw new Error("安装包大小不匹配");
        chunks.push(Uint8Array.from(chunk.value));
        progress(received / size);
      }
    } catch (error) { await reader.cancel(); throw error; } finally { reader.releaseLock(); }
    const blob = new Blob(chunks, { type: "application/zip" });
    if (received !== size || hex(await sha256Digest(await blob.arrayBuffer())) !== grant.sha256) throw new Error("安装包完整性校验失败，请重新下载");
    return { blob, filename: `BomanaEnhanced-${version}-windows-amd64.zip` };
  } finally { secret.fill(0); }
}

function base64url(bytes: Uint8Array): string { return btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", ""); }
function hex(bytes: Uint8Array): string { return Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join(""); }
