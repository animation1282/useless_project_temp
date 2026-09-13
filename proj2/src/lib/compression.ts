import { deflateSync, inflateSync } from "fflate";

/** Synchronous raw-deflate helpers (fflate, works in browser + vitest/node). */
export function deflateRaw(data: Uint8Array): Uint8Array {
  return deflateSync(data, { level: 9 });
}

export function inflateRaw(data: Uint8Array): Uint8Array {
  return inflateSync(data);
}

/** Best-effort: returns deflated bytes only if strictly smaller, else original. */
export function compressIfSmaller(data: Uint8Array): { stored: Uint8Array; deflated: boolean } {
  if (data.length === 0) return { stored: data, deflated: false };
  try {
    const out = deflateRaw(data);
    if (out.length < data.length) return { stored: out, deflated: true };
  } catch {
    // fall through to raw
  }
  return { stored: data, deflated: false };
}

export function decompressIfNeeded(stored: Uint8Array, deflated: boolean): Uint8Array {
  if (!deflated) return stored;
  try {
    return inflateRaw(stored);
  } catch {
    throw new Error("deflate decompression failed — data corrupted");
  }
}
