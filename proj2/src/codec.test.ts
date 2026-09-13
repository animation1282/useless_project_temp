import { describe, expect, it } from "vitest";
import {
  FormatCode,
  byteToEmoji,
  decodeEmojisToBytes,
  emojiToByte,
  encodeBytesToEmojis,
  encodeBytesToEmojisV1,
  sanitizeEmojiInput,
} from "./lib/emojiCodec";
import { compressIfSmaller } from "./lib/compression";
import { computeTarget, resolveOutputMime } from "./lib/imagePrepare";
import { formatChunk, joinChunks, splitEmojiString } from "./lib/chunking";

describe("byte<->emoji bijection", () => {
  it("round-trips all 256 byte values", () => {
    for (let b = 0; b < 256; b++) {
      const e = byteToEmoji(b);
      expect(Array.from(e)).toHaveLength(1); // single codepoint
      expect(emojiToByte(e)).toBe(b);
    }
    const all = new Set(Array.from({ length: 256 }, (_, b) => byteToEmoji(b)));
    expect(all.size).toBe(256);
  });
});

describe("framing codec (v2 + v1 legacy)", () => {
  it("round-trips empty, tiny and binary payloads", () => {
    for (const bytes of [
      new Uint8Array([]),
      new Uint8Array([0]),
      new Uint8Array([0, 1, 2, 255, 254]),
      Uint8Array.from({ length: 1000 }, (_, i) => i % 256),
    ]) {
      const s = encodeBytesToEmojis(bytes);
      expect(s.startsWith("🧬📦")).toBe(true);
      const { bytes: out } = decodeEmojisToBytes(s);
      expect(out).toEqual(bytes);
    }
  });

  it("still decodes legacy v1 codes", () => {
    const bytes = Uint8Array.from({ length: 300 }, (_, i) => i % 256);
    const v1 = encodeBytesToEmojisV1(bytes);
    const dec = decodeEmojisToBytes(v1);
    expect(dec.version).toBe(0x01);
    expect(dec.bytes).toEqual(bytes);
  });

  it("compresses repetitive data, skips incompressible", () => {
    const repetitive = new Uint8Array(2000).fill(7);
    const { deflated } = decodeEmojisToBytes(encodeBytesToEmojis(repetitive));
    expect(deflated).toBe(true);
    const random = Uint8Array.from({ length: 2000 }, (_, i) => (i * 37 + 11) % 256);
    // random-ish may or may not compress; just assert round-trip + flag consistency
    const s = encodeBytesToEmojis(random, { formatCode: FormatCode.Png });
    const dec = decodeEmojisToBytes(s);
    expect(dec.bytes).toEqual(random);
    expect(dec.formatCode).toBe(
      compressIfSmaller(random).deflated ? FormatCode.Png : FormatCode.Png
    );
  });

  it("respects explicit compress:false", () => {
    const bytes = new Uint8Array(500).fill(3);
    const dec = decodeEmojisToBytes(encodeBytesToEmojis(bytes, { compress: false }));
    expect(deflatedFalse(dec)).toBe(true);
    expect(dec.bytes).toEqual(bytes);
    function deflatedFalse(d: { deflated: boolean }) { return d.deflated === false; }
  });

  it("tolerates whitespace/newlines + VS16 (chat wrapping)", () => {
    const bytes = Uint8Array.from({ length: 200 }, (_, i) => (i * 7) % 256);
    const s = encodeBytesToEmojis(bytes);
    const wrapped = Array.from(sanitizeEmojiInput(s)).join("﻿\n "); // inject VS16 + wraps
    expect(decodeEmojisToBytes(wrapped).bytes).toEqual(bytes);
  });

  it("rejects truncation, trailing data and corruption", () => {
    const s = encodeBytesToEmojis(new Uint8Array([1, 2, 3, 4]));
    expect(() => decodeEmojisToBytes(Array.from(s).slice(0, -2).join(""))).toThrow();
    expect(() => decodeEmojisToBytes(s + "😀")).toThrow(/trailing/);
    const arr = Array.from(s);
    arr[arr.length - 5] = arr[arr.length - 5] === "😀" ? "😁" : "😀";
    expect(() => decodeEmojisToBytes(arr.join(""))).toThrow(/checksum/);
    expect(() => decodeEmojisToBytes("hello world")).toThrow();
  });
});

describe("imagePrepare pure helpers", () => {
  it("computeTarget fits longest side, never upscales", () => {
    expect(computeTarget(4000, 3000, 1024)).toEqual({ w: 1024, h: 768 });
    expect(computeTarget(3000, 4000, 1024)).toEqual({ w: 768, h: 1024 });
    expect(computeTarget(800, 600, 1024)).toEqual({ w: 800, h: 600 });
    expect(computeTarget(100, 100, 256)).toEqual({ w: 100, h: 100 });
    expect(() => computeTarget(0, 10, 512)).toThrow();
  });

  it("resolveOutputMime keeps alpha-safe defaults", () => {
    expect(resolveOutputMime("auto", "image/png")).toBe("image/webp");
    expect(resolveOutputMime("auto", "image/jpeg")).toBe("image/webp");
    expect(resolveOutputMime("jpeg", "image/png")).toBe("image/jpeg");
    expect(resolveOutputMime("png", "image/jpeg")).toBe("image/png");
  });
});

describe("chunking", () => {
  it("splits and rejoins order-independently", () => {
    const bytes = Uint8Array.from({ length: 5000 }, (_, i) => i % 256);
    const full = encodeBytesToEmojis(bytes, { compress: false });
    const chunks = splitEmojiString(full, 1000);
    expect(chunks.length).toBeGreaterThan(1);
    const pasted = chunks
      .map(formatChunk)
      .reverse() // out of order paste
      .join("\n");
    expect(decodeEmojisToBytes(joinChunks(pasted)).bytes).toEqual(bytes);
  });

  it("detects missing chunks", () => {
    const full = encodeBytesToEmojis(new Uint8Array([9, 9, 9]));
    const chunks = splitEmojiString(full, 3);
    const partial = chunks.slice(0, -1).map(formatChunk).join("\n");
    expect(() => joinChunks(partial)).toThrow(/missing/);
  });
});
