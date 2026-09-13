# 🧬 EmojiPipe — image ↔ emoji (lossless) data transfer

TypeScript web app (Vite + React, client-only) that transfers **any file as emojis** and decodes it back bit-for-bit.

## How it works

**Codec** (`src/lib/emojiCodec.ts`): unconventional but strictly lossless base-256 encoding.

- Alphabet: 1 byte = 1 emoji via `String.fromCodePoint(0x1F600 + byte)` → range U+1F600–U+1F6FF (256 single-codepoint pictographs, no ZWJ/skin-tone sequences, so `Array.from` splits safely).
- Framing v2: `🧬📦 + VERSION(0x02) + FLAGS(1: deflate bit + src-format hint) + LENGTH(4, stored len) + DATA + CRC32(4 over stored)`. v1 codes still decode.
- Safest packing: deflate-raw via `fflate`, kept only if smaller (auto). Big win on screenshots/text PNGs, ~0% on JPEG/WebP (then skipped).
- Cost: ~4× UTF-8 size blowup; 5MB cap on payload.

**Optimize** (`src/lib/imagePrepare.ts`, lossy, manual sliders): max-dimension 256–2048 (longest-side fit, never upscale) + format auto/webp/jpeg/png + quality 0.50–0.95. Canvas `drawImage` + `toBlob` with webp→jpeg→png fallback; JPEG flattens alpha onto white. UI defaults to optimized for images with an original/optimized toggle — decode restores the optimized image.

**Chunking** (`src/lib/chunking.ts`): splits the emoji string by codepoint count into `i/N|<emojis>` messages for Discord/SMS-style limits; reassembly is order-independent and reports missing chunks.

## Run

```bash
npm install
npm run dev      # UI: Encode tab (drop file → copy emojis) / Decode tab (paste → restore)
npm test         # vitest: 256-byte bijection, round-trips, corruption/truncation, chunking
npm run build
```

## Other unconventional transfer ideas (v2 candidates)

1. **Zero-width steganography** — hide bits in normal text with `U+200B=0, U+200C=1, U+200D=sep, U+FEFF=end`. Looks like empty text, decodes to bytes. Same framing (length+CRC) applies.
2. **Cross-media codes** — bytes→color PNG (3 bytes/pixel + header row), bytes→WAV spectrogram / SSTV-style audio, text→QR tile grid. Implementation: `Canvas`/`WebAudio` encode, `getImageData`/`FFT` decode.
3. **Esoteric base encodings** — base-2048 with CJK + emoji alphabet (~11 bits/char, denser than base64), Braille `U+2800+P` (8 dots = 1 byte, very compact visually), DNA `ACGT` (2 bits/base, fun for bio-themed channels).
4. **Protocol mimicry demo** — chunk payload into fake `TXT`/`DNS`-looking labels or `ICMP`-style hex dumps with sequence numbers, reassemble on receipt. Shows how exfil hides in plain sight (educational only).
5. **Visual (lossy) emoji mosaic** — downsample image → map each cell's avg color to closest emoji (e.g. 🟥🟩🟦🍋). Recognizable art but *not* decodable; keep as separate mode so users don't confuse it with the lossless codec.

## Limits / warnings

- Some messengers normalize or substitute emojis (test WhatsApp/Discord/Slack before relying on them).
- Anyone holding the emojis holds the bytes — CRC detects corruption, not tampering. Encrypt first if sensitive.
