// Checks an evidence package with nothing but Node: a minimal ZIP reader (stored and
// deflated entries, no ZIP64), SHA-256 and Ed25519 from node:crypto. This is what an
// auditor's own tooling would do, independent of dsec-metrics' Python verifier.
import { createHash, createPublicKey, verify } from "node:crypto";
import { readFileSync } from "node:fs";
import { inflateRawSync } from "node:zlib";

/** @param {Buffer} buf @returns {Map<string, Buffer>} */
function readZip(buf) {
  let eocd = -1;
  for (let i = buf.length - 22; i >= Math.max(0, buf.length - 65557); i--) {
    if (buf.readUInt32LE(i) === 0x06054b50) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) throw new Error("not a ZIP file");
  const count = buf.readUInt16LE(eocd + 10);
  let offset = buf.readUInt32LE(eocd + 16);
  const files = new Map();
  for (let n = 0; n < count; n++) {
    if (buf.readUInt32LE(offset) !== 0x02014b50) throw new Error("bad central directory");
    const method = buf.readUInt16LE(offset + 10);
    const compressed = buf.readUInt32LE(offset + 20);
    const nameLength = buf.readUInt16LE(offset + 28);
    const extraLength = buf.readUInt16LE(offset + 30);
    const commentLength = buf.readUInt16LE(offset + 32);
    const local = buf.readUInt32LE(offset + 42);
    const name = buf.toString("utf8", offset + 46, offset + 46 + nameLength);
    const start = local + 30 + buf.readUInt16LE(local + 26) + buf.readUInt16LE(local + 28);
    const data = buf.subarray(start, start + compressed);
    files.set(name, method === 8 ? inflateRawSync(data) : Buffer.from(data));
    offset += 46 + nameLength + extraLength + commentLength;
  }
  return files;
}

/**
 * Returns a list of problems; empty means the package verifies.
 * @param {Uint8Array} bytes
 * @param {string} fingerprint
 */
export function checkPackage(bytes, fingerprint) {
  const problems = [];
  let files;
  try {
    files = readZip(Buffer.from(bytes));
  } catch (err) {
    return [`unreadable: ${String(err)}`];
  }
  const manifestBytes = files.get("manifest.json");
  const signature = files.get("manifest.sig");
  if (!manifestBytes || !signature) return ["manifest or signature missing"];
  let manifest;
  try {
    manifest = JSON.parse(manifestBytes.toString("utf8"));
  } catch {
    return ["manifest is not JSON"];
  }
  const raw = Buffer.from(manifest.signing.public_key, "base64");
  if (createHash("sha256").update(raw).digest("hex") !== fingerprint) {
    problems.push("signing key fingerprint differs");
  }
  // Ed25519 SubjectPublicKeyInfo is a fixed 12-byte prefix and the 32-byte key.
  const der = Buffer.concat([Buffer.from("302a300506032b6570032100", "hex"), raw]);
  const key = createPublicKey({ key: der, format: "der", type: "spki" });
  const sig = Buffer.from(signature.toString("ascii").trim(), "base64");
  if (!verify(null, manifestBytes, key, sig)) problems.push("signature does not match");
  const listed = new Set(["manifest.json", "manifest.sig"]);
  for (const f of manifest.files) {
    listed.add(f.path);
    const data = files.get(f.path);
    if (!data) problems.push(`${f.path} missing`);
    else if (data.length !== f.size) problems.push(`${f.path} size differs`);
    else if (createHash("sha256").update(data).digest("hex") !== f.sha256) {
      problems.push(`${f.path} hash differs`);
    }
  }
  for (const name of files.keys()) if (!listed.has(name)) problems.push(`${name} not listed`);
  return problems;
}

/** The manifest's report block, for assertions. @param {Uint8Array} bytes */
export function reportOf(bytes) {
  const manifest = readZip(Buffer.from(bytes)).get("manifest.json");
  return manifest ? JSON.parse(manifest.toString("utf8")).report : null;
}

/** Flip one byte inside the stored manifest.json of a copy of the package. @param {Uint8Array} bytes */
export function flipManifestByte(bytes) {
  const copy = Buffer.from(bytes);
  const at = copy.indexOf(Buffer.from('"format"'));
  if (at < 0) {
    // Deflated manifest: flip a byte in the middle of the archive instead.
    copy[Math.floor(copy.length / 2)] ^= 0xff;
  } else {
    copy[at + 2] ^= 0x01;
  }
  return copy;
}

/** The development dev-admin password; e2e-auditor shares it. */
export function devPassword() {
  return readFileSync(
    new URL("../../deploy/compose/secrets/dev_admin_password", import.meta.url),
    "utf8",
  ).trim();
}
