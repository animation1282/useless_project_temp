import { useEffect, useMemo, useState } from "react";
import {
  FormatCode,
  decodeEmojisToBytes,
  encodeBytesToEmojis,
  emojiCount,
  estimatedUtf8Bytes,
  formatCodeForMime,
  MAX_PAYLOAD_BYTES,
} from "./lib/emojiCodec";
import { formatChunk, joinChunks, splitEmojiString } from "./lib/chunking";
import {
  DEFAULT_OPTIMIZE,
  prepareImage,
  probeDimensions,
  type OptimizeFormat,
} from "./lib/imagePrepare";
import "./App.css";

function sniffMime(b: Uint8Array): string {
  if (b.length >= 8 && b[0] === 0x89 && b[1] === 0x50 && b[2] === 0x4e && b[3] === 0x47)
    return "image/png";
  if (b.length >= 3 && b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff) return "image/jpeg";
  if (b.length >= 6 && b[0] === 0x47 && b[1] === 0x49 && b[2] === 0x46) return "image/gif";
  if (
    b.length >= 12 &&
    b[0] === 0x52 && b[1] === 0x49 && b[2] === 0x46 && b[3] === 0x46 &&
    b[8] === 0x57 && b[9] === 0x45 && b[10] === 0x42 && b[11] === 0x50
  )
    return "image/webp";
  if (b.length >= 2 && b[0] === 0x42 && b[1] === 0x4d) return "image/bmp";
  return "application/octet-stream";
}

function extFor(mime: string): string {
  switch (mime) {
    case "image/png": return "png";
    case "image/jpeg": return "jpg";
    case "image/gif": return "gif";
    case "image/webp": return "webp";
    case "image/bmp": return "bmp";
    default: return "bin";
  }
}

function kb(n: number): string {
  return n < 1024 ? `${n}B` : `${(n / 1024).toFixed(1)}KB`;
}

function downloadBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

interface OptimizedState {
  bytes: Uint8Array;
  mime: string;
  w: number;
  h: number;
}

export default function App() {
  const [tab, setTab] = useState<"encode" | "decode">("encode");

  // source file
  const [fileName, setFileName] = useState("");
  const [originalBytes, setOriginalBytes] = useState<Uint8Array | null>(null);
  const [originalMime, setOriginalMime] = useState("");
  const [originalDims, setOriginalDims] = useState<{ w: number; h: number } | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  // manual optimize sliders
  const [useOptimized, setUseOptimized] = useState(true);
  const [maxDim, setMaxDim] = useState(DEFAULT_OPTIMIZE.maxDim);
  const [format, setFormat] = useState<OptimizeFormat>(DEFAULT_OPTIMIZE.format);
  const [quality, setQuality] = useState(DEFAULT_OPTIMIZE.quality);

  const [optimized, setOptimized] = useState<OptimizedState | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [prepareErr, setPrepareErr] = useState("");

  // encoded output
  const [emojiOut, setEmojiOut] = useState("");
  const [encodeErr, setEncodeErr] = useState("");
  const [encodeMeta, setEncodeMeta] = useState("");
  const [chunkSize, setChunkSize] = useState(500);

  // decode state
  const [decodeInput, setDecodeInput] = useState("");
  const [decodeErr, setDecodeErr] = useState("");
  const [decodedUrl, setDecodedUrl] = useState<string | null>(null);
  const [decodedInfo, setDecodedInfo] = useState("");

  const isImage = originalMime.startsWith("image/") || (originalBytes ? sniffMime(originalBytes).startsWith("image/") : false);

  const chunks = useMemo(
    () => (emojiOut ? splitEmojiString(emojiOut, chunkSize) : []),
    [emojiOut, chunkSize]
  );

  async function handleFile(f: File) {
    setEncodeErr(""); setPrepareErr(""); setEmojiOut(""); setEncodeMeta("");
    setOptimized(null); setOriginalDims(null);
    setFileName(f.name);
    if (f.size > MAX_PAYLOAD_BYTES) {
      setEncodeErr(`File too large: ${(f.size / 1024 / 1024).toFixed(2)}MB (cap 5MB) — try Optimize below first`);
      setOriginalBytes(null); setPreviewUrl(null);
      return;
    }
    const buf = new Uint8Array(await f.arrayBuffer());
    const mime = f.type || sniffMime(buf);
    setOriginalBytes(buf);
    setOriginalMime(mime);
    setPreviewUrl(URL.createObjectURL(new Blob([buf as BlobPart], { type: mime })));
    if (mime.startsWith("image/")) {
      try {
        setOriginalDims(await probeDimensions(new Blob([buf as BlobPart], { type: mime })));
      } catch { /* non-fatal */ }
    }
  }

  // Debounced lossy optimize (manual sliders only, no auto-fit).
  useEffect(() => {
    if (!originalBytes || !isImage || !useOptimized) {
      setOptimized(null); setPreparing(false);
      return;
    }
    let cancelled = false;
    setPreparing(true);
    setPrepareErr("");
    const t = setTimeout(() => {
      (async () => {
        try {
          const src = new Blob([originalBytes as BlobPart], { type: originalMime });
          const p = await prepareImage(src, originalMime, { maxDim, format, quality });
          if (!cancelled) setOptimized({ bytes: p.bytes, mime: p.mime, w: p.w, h: p.h });
        } catch (e) {
          if (!cancelled) {
            setOptimized(null);
            setPrepareErr(e instanceof Error ? e.message : String(e));
          }
        } finally {
          if (!cancelled) setPreparing(false);
        }
      })();
    }, 250);
    return () => { cancelled = true; clearTimeout(t); };
  }, [originalBytes, isImage, useOptimized, maxDim, format, quality, originalMime]);

  // Encode active bytes (optimized if available, else original) with safest packing.
  useEffect(() => {
    if (!originalBytes) { setEmojiOut(""); setEncodeMeta(""); return; }
    const active = useOptimized && optimized ? optimized.bytes : originalBytes;
    const activeMime = useOptimized && optimized ? optimized.mime : originalMime;
    try {
      const out = encodeBytesToEmojis(active, { formatCode: formatCodeForMime(activeMime) });
      setEmojiOut(out);
      setEncodeErr("");
      const dec = decodeEmojisToBytes(out);
      const ratio = active.length === 0 ? "—" : `${((dec.storedLength / active.length) * 100).toFixed(0)}% of image bytes`;
      setEncodeMeta(
        `${dec.deflated ? "deflate ON" : "deflate skipped (incompressible)"} • stored ${kb(dec.storedLength)} (${ratio}) • v${dec.version}`
      );
    } catch (e) {
      setEmojiOut("");
      setEncodeMeta("");
      setEncodeErr(e instanceof Error ? e.message : String(e));
    }
  }, [originalBytes, optimized, useOptimized, originalMime]);

  const activeBytes = useOptimized && optimized ? optimized.bytes : originalBytes;
  const activeLabel = useOptimized && optimized
    ? `optimized ${optimized.w}×${optimized.h} ${optimized.mime}`
    : originalBytes ? `original${originalDims ? ` ${originalDims.w}×${originalDims.h}` : ""} ${originalMime}` : "";

  function handleDecode() {
    setDecodeErr("");
    setDecodedUrl(null);
    setDecodedInfo("");
    try {
      const full = joinChunks(decodeInput);
      const { bytes, deflated, version, storedLength, formatCode } = decodeEmojisToBytes(full);
      const mime = sniffMime(bytes);
      const blob = new Blob([bytes as BlobPart], { type: mime });
      const url = URL.createObjectURL(blob);
      setDecodedUrl(mime.startsWith("image/") ? url : null);
      const fmtName = (Object.keys(FormatCode) as Array<keyof typeof FormatCode>).find((k) => FormatCode[k] === formatCode) ?? "Unknown";
      setDecodedInfo(`${bytes.length} bytes • ${mime} • v${version} • ${deflated ? `deflated (stored ${storedLength})` : "raw"} • src:${fmtName} • ${emojiCount(full)} emojis`);
      (handleDecode as unknown as { _blob?: Blob })._blob = blob;
      (handleDecode as unknown as { _mime?: string })._mime = mime;
    } catch (e) {
      setDecodeErr(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="wrap">
      <header>
        <h1>🧬 EmojiPipe — image ↔ emoji transfer</h1>
        <p className="sub">
          Lossless codec: <code>1 byte = 1 emoji</code> (U+1F600–U+1F6FF) + magic <code>🧬📦</code> + flags + length + CRC32.
          Images can be lossy-optimized first to shrink the emoji count.
        </p>
        <div className="tabs">
          <button className={tab === "encode" ? "active" : ""} onClick={() => setTab("encode")}>Encode</button>
          <button className={tab === "decode" ? "active" : ""} onClick={() => setTab("decode")}>Decode</button>
        </div>
      </header>

      {tab === "encode" && (
        <section className="card">
          <h2>1. Drop an image / any file (≤5MB)</h2>
          <div
            className="drop"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) void handleFile(f); }}
          >
            <input
              type="file"
              accept="image/*,*/*"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) void handleFile(f); }}
            />
            <span>{fileName || "drag & drop or click to choose"}</span>
          </div>
          {previewUrl && <img className="preview" src={previewUrl} alt="original preview" />}

          {originalBytes && isImage && (
            <>
              <h2>2. Resize / recompress (lossy, manual)</h2>
              <label className="check">
                <input type="checkbox" checked={useOptimized} onChange={(e) => setUseOptimized(e.target.checked)} />
                Use optimized version (decode restores the optimized image, not the original)
              </label>
              <div className="sliders">
                <label>Max dimension: {maxDim}px
                  <input type="range" min={256} max={2048} step={64} value={maxDim}
                    disabled={!useOptimized} onChange={(e) => setMaxDim(Number(e.target.value))} />
                </label>
                <label>Format:
                  <select value={format} disabled={!useOptimized}
                    onChange={(e) => setFormat(e.target.value as OptimizeFormat)}>
                    <option value="auto">auto (webp, alpha-safe)</option>
                    <option value="webp">webp</option>
                    <option value="jpeg">jpeg (no alpha)</option>
                    <option value="png">png (largest)</option>
                  </select>
                </label>
                <label>Quality: {quality.toFixed(2)}
                  <input type="range" min={0.5} max={0.95} step={0.05} value={quality}
                    disabled={!useOptimized || format === "png"} onChange={(e) => setQuality(Number(e.target.value))} />
                </label>
              </div>
              {preparing && <p className="meta">Optimizing…</p>}
              {prepareErr && <p className="err">Optimize failed ({prepareErr}) — falling back to original.</p>}
              {optimized && useOptimized && (
                <div>
                  <img className="preview" src={URL.createObjectURL(new Blob([optimized.bytes as BlobPart], { type: optimized.mime }))} alt="optimized preview" />
                  <p className="meta">
                    {originalBytes.length}B{originalDims ? ` ${originalDims.w}×${originalDims.h}` : ""} →{" "}
                    {optimized.bytes.length}B {optimized.w}×{optimized.h} {optimized.mime} (
                    {originalBytes.length ? ((optimized.bytes.length / originalBytes.length) * 100).toFixed(0) : "—"}%)
                  </p>
                </div>
              )}
            </>
          )}

          {activeBytes && (
            <p className="meta">
              Encoding {activeLabel} • {activeBytes.length} bytes → {emojiCount(emojiOut)} emojis • ~
              {(estimatedUtf8Bytes(emojiOut) / 1024).toFixed(1)}KB UTF-8 • {encodeMeta}
            </p>
          )}
          {encodeErr && <p className="err">{encodeErr}</p>}
          {emojiOut && (
            <>
              <h2>{isImage ? "3" : "2"}. Emoji payload (copy / send as text)</h2>
              <textarea rows={6} readOnly value={emojiOut} />
              <div className="row">
                <button onClick={() => void navigator.clipboard.writeText(emojiOut)}>Copy emojis</button>
                <button onClick={() => downloadBlob(new Blob([emojiOut], { type: "text/plain" }), (fileName || "image") + ".emoji.txt")}>
                  Download .txt
                </button>
              </div>
              <h2>{isImage ? "4" : "3"}. Split for chat limits</h2>
              <label>Max emojis per message:{" "}
                <input type="number" min={50} max={1900} value={chunkSize}
                  onChange={(e) => setChunkSize(Math.max(50, Number(e.target.value) || 500))} />
              </label>
              <p className="meta">{chunks.length} message(s), each prefixed <code>i/N|</code></p>
              <textarea rows={Math.min(8, chunks.length + 1)} readOnly
                value={chunks.map(formatChunk).join("\n")} />
              <div className="row">
                <button onClick={() => void navigator.clipboard.writeText(chunks.map(formatChunk).join("\n"))}>
                  Copy all chunks
                </button>
              </div>
            </>
          )}
        </section>
      )}

      {tab === "decode" && (
        <section className="card">
          <h2>1. Paste emoji code or chunked messages</h2>
          <textarea rows={8} placeholder="🧬📦…  or  1/3|🧬…  2/3|…"
            value={decodeInput} onChange={(e) => setDecodeInput(e.target.value)} />
          <div className="row">
            <button onClick={handleDecode}>Decode</button>
            <label className="filebtn">Upload .txt
              <input type="file" accept=".txt,text/plain" hidden
                onChange={async (e) => {
                  const f = e.target.files?.[0];
                  if (f) setDecodeInput(await f.text());
                }} />
            </label>
          </div>
          {decodeErr && <p className="err">{decodeErr}</p>}
          {decodedInfo && <p className="meta ok">✔ {decodedInfo}</p>}
          {decodedUrl && <img className="preview" src={decodedUrl} alt="decoded" />}
          {decodedInfo && (
            <div className="row">
              <button onClick={() => {
                const blob = (handleDecode as unknown as { _blob?: Blob })._blob;
                const mime = (handleDecode as unknown as { _mime?: string })._mime ?? "application/octet-stream";
                if (blob) downloadBlob(blob, `restored.${extFor(mime)}`);
              }}>Download restored file</button>
            </div>
          )}
          <details>
            <summary>How decoding works</summary>
            <p>Prefixes <code>i/N|</code> stripped + ordered → whitespace/VS16 removed → magic <code>🧬📦</code> + version/flags checked → length + CRC32 verified → inflate if flagged → image blob.</p>
          </details>
        </section>
      )}

      <footer>
        <p>Unconventional ≠ insecure: anyone holding the emojis holds the bytes. CRC detects corruption, not tampering.</p>
      </footer>
    </div>
  );
}
