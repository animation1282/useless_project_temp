/**
 * Chunking for chat/clipboard limits (e.g. Discord 2000 chars, SMS, tweets).
 * Splits an emoji string (counted in codepoints) into numbered ASCII-wrapped
 * chunks:  "i/N|<emojis>"  so reassembly just strips the prefix and joins.
 */
import { sanitizeEmojiInput } from "./emojiCodec";

export interface EmojiChunk {
  index: number; // 1-based
  total: number;
  payload: string; // raw emojis, no prefix
}

export function splitEmojiString(full: string, maxEmojisPerChunk = 1500): EmojiChunk[] {
  const clean = sanitizeEmojiInput(full);
  const arr = Array.from(clean);
  if (arr.length === 0) return [];
  const chunks: EmojiChunk[] = [];
  const total = Math.ceil(arr.length / maxEmojisPerChunk);
  for (let i = 0; i < total; i++) {
    const slice = arr.slice(i * maxEmojisPerChunk, (i + 1) * maxEmojisPerChunk).join("");
    chunks.push({ index: i + 1, total, payload: slice });
  }
  return chunks;
}

export function formatChunk(c: EmojiChunk): string {
  return `${c.index}/${c.total}|${c.payload}`;
}

/** Parse one or many pasted chunk lines back into the full emoji string. Order-independent. */
export function joinChunks(pasted: string): string {
  const lines = pasted
    .split(/\n+/)
    .map((l) => l.trim())
    .filter(Boolean);
  if (lines.length === 0) throw new Error("no chunks found");
  // Single unprefixed blob = no chunking used.
  if (lines.length === 1 && !/^\d+\/\d+\|/.test(lines[0])) {
    return sanitizeEmojiInput(lines[0]);
  }
  const parsed: EmojiChunk[] = lines.map((line) => {
    const m = line.match(/^(\d+)\/(\d+)\|(.*)$/s);
    if (!m) throw new Error(`bad chunk line (expected "i/N|<emojis>"): ${line.slice(0, 40)}…`);
    return { index: Number(m[1]), total: Number(m[2]), payload: sanitizeEmojiInput(m[3]) };
  });
  const total = parsed[0].total;
  if (!parsed.every((p) => p.total === total)) throw new Error("chunk totals disagree");
  if (parsed.length !== total) {
    const have = new Set(parsed.map((p) => p.index));
    const missing = Array.from({ length: total }, (_, i) => i + 1).filter((i) => !have.has(i));
    throw new Error(`missing chunks: ${missing.join(", ")} (have ${parsed.length}/${total})`);
  }
  parsed.sort((a, b) => a.index - b.index);
  return parsed.map((p) => p.payload).join("");
}
