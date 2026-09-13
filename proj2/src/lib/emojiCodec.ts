/**
 * Lossless byte <-> emoji codec (v1 + v2).
 *
 * Alphabet (unchanged, safest): 1 byte = 1 emoji,
 *   byte b -> String.fromCodePoint(0x1F600 + b)  // U+1F600..U+1F6FF
 *
 * v1 framing: MAGIC + VERSION(0x01) + LENGTH(4) + DATA(N) + CRC32(4)
 * v2 framing: MAGIC + VERSION(0x02) + FLAGS(1) + LENGTH(4, stored len) + DATA + CRC32(4, over stored)
 *   FLAGS bit0 = deflated (deflate-raw via fflate); bits1-3 = source format code.
 *   LENGTH/CRC refer to STORED bytes; decode inflates afterwards.
 *
 * Encode defaults to safest packing: try deflate, keep it only if smaller.
 * Decode accepts v1 (legacy) and v2.
 */

import { compressIfSmaller, decompressIfNeeded } from "./compression";

export const DATA_BASE = 0x1f600;
export const DATA_RANGE = 256;
export const MAGIC = "🧬📦"; // U+1F9EC U+1F4E6 — outside data range
export const VERSION_V1 = 0x01;
export const VERSION_V2 = 0x02;
export const MAX_PAYLOAD_BYTES = 5 * 1024 * 1024;

export const FLAG_DEFLATED = 0x01;
const FORMAT_SHIFT = 1;
const FORMAT_MASK = 0x07;

/** Source-format hint stored in FLAGS (display/diagnostics only, not required to decode). */
export const FormatCode = {
  Unknown: 0,
  Png: 1,
  Jpeg: 2,
  Webp: 3,
  Gif: 4,
  Bmp: 5,
} as const;
export type FormatCode = (typeof FormatCode)[keyof typeof FormatCode];

export function formatCodeForMime(mime: string): FormatCode {
  switch (mime) {
    case "image/png": return FormatCode.Png;
    case "image/jpeg": return FormatCode.Jpeg;
    case "image/webp": return FormatCode.Webp;
    case "image/gif": return FormatCode.Gif;
    case "image/bmp": return FormatCode.Bmp;
    default: return FormatCode.Unknown;
  }
}

const MAGIC_CODEPOINTS = Array.from(MAGIC);

export function byteToEmoji(b: number): string {
  if (!Number.isInteger(b) || b < 0 || b > 255) throw new Error(`byte out of range: ${b}`);
  return String.fromCodePoint(DATA_BASE + b);
}

export function emojiToByte(ch: string): number {
  const cps = Array.from(ch);
  if (cps.length !== 1) throw new Error(`expected single emoji, got: ${JSON.stringify(ch)}`);
  const cp = cps[0].codePointAt(0)!;
  const b = cp - DATA_BASE;
  if (b < 0 || b > 255) throw new Error(`emoji out of data range: U+${cp.toString(16)}`);
  return b;
}

/** CRC32 (IEEE). */
const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

export function crc32(data: Uint8Array): number {
  let crc = 0xffffffff;
  for (let i = 0; i < data.length; i++) {
    crc = CRC_TABLE[(crc ^ data[i]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function uint32ToEmojis(v: number): string {
  return (
    byteToEmoji((v >>> 24) & 0xff) +
    byteToEmoji((v >>> 16) & 0xff) +
    byteToEmoji((v >>> 8) & 0xff) +
    byteToEmoji(v & 0xff)
  );
}

function emojisToUint32(arr: string[], offsetCodepoints: number): number {
  const b0 = emojiToByte(arr[offsetCodepoints]);
  const b1 = emojiToByte(arr[offsetCodepoints + 1]);
  const b2 = emojiToByte(arr[offsetCodepoints + 2]);
  const b3 = emojiToByte(arr[offsetCodepoints + 3]);
  return ((b0 * 256 ** 3 + b1 * 256 ** 2 + b2 * 256 + b3) >>> 0) >>> 0;
}

function bytesToEmojisRaw(data: Uint8Array): string {
  let out = "";
  const CHUNK = 8192;
  for (let i = 0; i < data.length; i += CHUNK) {
    let part = "";
    const end = Math.min(i + CHUNK, data.length);
    for (let j = i; j < end; j++) part += String.fromCodePoint(DATA_BASE + data[j]);
    out += part;
  }
  return out;
}

/** Normalize pasted text: drop whitespace + VS16, keep everything else. */
export function sanitizeEmojiInput(input: string): string {
  return input.replace(/[\s\uFE0F]+/g, "");
}

export interface EncodeOptions {
  /** default true: try deflate, keep only if smaller */
  compress?: boolean;
  /** source-format hint for FLAGS, default Unknown */
  formatCode?: FormatCode;
}

export function encodeBytesToEmojis(data: Uint8Array, opts: EncodeOptions = {}): string {
  if (data.length > MAX_PAYLOAD_BYTES) {
    throw new Error(`payload too large: ${data.length} bytes (cap ${MAX_PAYLOAD_BYTES})`);
  }
  const compress = opts.compress !== false;
  const formatCode = opts.formatCode ?? FormatCode.Unknown;
  const { stored, deflated } = compress ? compressIfSmaller(data) : { stored: data, deflated: false };
  if (stored.length > MAX_PAYLOAD_BYTES) {
    throw new Error(`payload too large: ${stored.length} bytes (cap ${MAX_PAYLOAD_BYTES})`);
  }
  const flags = (deflated ? FLAG_DEFLATED : 0) | ((formatCode & FORMAT_MASK) << FORMAT_SHIFT);
  return (
    MAGIC +
    byteToEmoji(VERSION_V2) +
    byteToEmoji(flags) +
    uint32ToEmojis(stored.length) +
    bytesToEmojisRaw(stored) +
    uint32ToEmojis(crc32(stored))
  );
}

/** Legacy v1 encoder (kept for compat tests / old decoders). */
export function encodeBytesToEmojisV1(data: Uint8Array): string {
  if (data.length > MAX_PAYLOAD_BYTES) throw new Error(`payload too large: ${data.length}`);
  return (
    MAGIC +
    byteToEmoji(VERSION_V1) +
    uint32ToEmojis(data.length) +
    bytesToEmojisRaw(data) +
    uint32ToEmojis(crc32(data))
  );
}

export interface DecodeResult {
  /** Original (inflated) bytes */
  bytes: Uint8Array;
  version: number;
  deflated: boolean;
  formatCode: FormatCode;
  /** Stored payload size (pre-inflate); useful for stats */
  storedLength: number;
}

function emojisToBytes(arr: string[], start: number, len: number): Uint8Array {
  const out = new Uint8Array(len);
  for (let i = 0; i < len; i++) out[i] = emojiToByte(arr[start + i]);
  return out;
}

function checkFraming(arr: string[], expectedTotal: number): void {
  if (arr.length < expectedTotal) {
    throw new Error(`truncated input: need ${expectedTotal} emojis, got ${arr.length}`);
  }
  if (arr.length > expectedTotal) {
    throw new Error(
      `trailing data: expected ${expectedTotal} emojis, got ${arr.length} (did you paste two codes together?)`
    );
  }
}

function verifyCrc(stored: Uint8Array, expectedCrc: number): void {
  const actual = crc32(stored);
  if (expectedCrc !== actual) {
    throw new Error(
      `checksum mismatch: expected ${expectedCrc.toString(16)}, got ${actual.toString(16)} — data corrupted in transit`
    );
  }
}

export function decodeEmojisToBytes(input: string): DecodeResult {
  const clean = sanitizeEmojiInput(input);
  const arr = Array.from(clean);

  if (arr.length < MAGIC_CODEPOINTS.length + 1 + 4 + 4) {
    throw new Error("input too short — missing header/checksum");
  }
  const magic = arr.slice(0, MAGIC_CODEPOINTS.length).join("");
  if (magic !== MAGIC) {
    throw new Error(`bad magic header — expected ${MAGIC}, input may be truncated or not an emoji-code`);
  }
  const version = emojiToByte(arr[MAGIC_CODEPOINTS.length]);

  if (version === VERSION_V1) {
    const headerLen = MAGIC_CODEPOINTS.length + 1;
    const payloadLen = emojisToUint32(arr, headerLen);
    if (payloadLen > MAX_PAYLOAD_BYTES) throw new Error(`declared payload too large: ${payloadLen} bytes`);
    checkFraming(arr, headerLen + 4 + payloadLen + 4);
    const dataStart = headerLen + 4;
    const stored = emojisToBytes(arr, dataStart, payloadLen);
    verifyCrc(stored, emojisToUint32(arr, dataStart + payloadLen));
    return { bytes: stored, version, deflated: false, formatCode: FormatCode.Unknown, storedLength: payloadLen };
  }

  if (version === VERSION_V2) {
    const headerLen = MAGIC_CODEPOINTS.length + 2; // version + flags
    if (arr.length < headerLen + 4 + 4) throw new Error("input too short — missing v2 header/checksum");
    const flags = emojiToByte(arr[MAGIC_CODEPOINTS.length + 1]);
    const deflated = (flags & FLAG_DEFLATED) !== 0;
    const formatCode = ((flags >> FORMAT_SHIFT) & FORMAT_MASK) as FormatCode;
    const storedLen = emojisToUint32(arr, headerLen);
    if (storedLen > MAX_PAYLOAD_BYTES) throw new Error(`declared payload too large: ${storedLen} bytes`);
    checkFraming(arr, headerLen + 4 + storedLen + 4);
    const dataStart = headerLen + 4;
    const stored = emojisToBytes(arr, dataStart, storedLen);
    verifyCrc(stored, emojisToUint32(arr, dataStart + storedLen));
    const bytes = decompressIfNeeded(stored, deflated);
    return { bytes, version, deflated, formatCode, storedLength: storedLen };
  }

  throw new Error(`unsupported version: ${version}`);
}

/** Helpers for file transfer. */
export async function encodeFileToEmojis(file: File | Blob, opts: EncodeOptions = {}): Promise<string> {
  const buf = new Uint8Array(await file.arrayBuffer());
  return encodeBytesToEmojis(buf, opts);
}

export function emojiCount(s: string): number {
  return Array.from(sanitizeEmojiInput(s)).length;
}

export function estimatedUtf8Bytes(s: string): number {
  return new TextEncoder().encode(s).length;
}
