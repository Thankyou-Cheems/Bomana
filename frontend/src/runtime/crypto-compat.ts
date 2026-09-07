export async function sha256Digest(bytes: ArrayBuffer | Uint8Array): Promise<Uint8Array> {
  const payload = bytes instanceof Uint8Array ? Uint8Array.from(bytes) : new Uint8Array(bytes);
  const subtle = globalThis.crypto?.subtle;
  if (subtle) {
    try {
      return new Uint8Array(await subtle.digest("SHA-256", payload));
    } catch {
      // RFC1918 HTTP pages are not secure contexts on iOS Safari.
    }
  }
  const { sha256 } = await import("@noble/hashes/sha2.js");
  return sha256(payload);
}

export async function verifyEd25519Signature(
  publicKey: ArrayBuffer | Uint8Array,
  signature: ArrayBuffer | Uint8Array,
  message: Uint8Array,
): Promise<boolean> {
  const keyBytes = publicKey instanceof Uint8Array ? Uint8Array.from(publicKey) : new Uint8Array(publicKey);
  const signatureBytes = signature instanceof Uint8Array ? Uint8Array.from(signature) : new Uint8Array(signature);
  const messageBytes = Uint8Array.from(message);
  const subtle = globalThis.crypto?.subtle;
  if (subtle) {
    try {
      const imported = await subtle.importKey("raw", keyBytes, { name: "Ed25519" }, false, ["verify"]);
      return await subtle.verify({ name: "Ed25519" }, imported, signatureBytes, messageBytes);
    } catch {
      // Use the bundled verifier when Web Crypto or Ed25519 is unavailable.
    }
  }
  try {
    const [ed25519, hashes] = await Promise.all([
      import("@noble/ed25519"),
      import("@noble/hashes/sha2.js"),
    ]);
    ed25519.hashes.sha512 = hashes.sha512;
    return ed25519.verify(signatureBytes, messageBytes, keyBytes, { zip215: false });
  } catch {
    return false;
  }
}
