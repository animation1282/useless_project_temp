/**
 * Lossy image optimize step (runs BEFORE the lossless emoji codec).
 * Pure Canvas API, no dependencies. computeTarget/resolveOutputMime are
 * pure and unit-testable in node; transcode needs a browser.
 */

export type OptimizeFormat = "auto" | "webp" | "jpeg" | "png";

export interface OptimizeOptions {
  maxDim: number; // 256..2048, longest side
  format: OptimizeFormat;
  quality: number; // 0.5..0.95 (webp/jpeg only)
}

export const DEFAULT_OPTIMIZE: OptimizeOptions = { maxDim: 1024, format: "auto", quality: 0.8 };

export function clampOptimize(o: Partial<OptimizeOptions>): OptimizeOptions {
  return {
    maxDim: Math.min(2048, Math.max(256, Math.round(o.maxDim ?? DEFAULT_OPTIMIZE.maxDim))),
    format: o.format ?? DEFAULT_OPTIMIZE.format,
    quality: Math.min(0.95, Math.max(0.5, o.quality ?? DEFAULT_OPTIMIZE.quality)),
  };
}

/** Longest-side fit, never upscale. Pure — safe to test in node. */
export function computeTarget(srcW: number, srcH: number, maxDim: number): { w: number; h: number } {
  if (!Number.isFinite(srcW) || !Number.isFinite(srcH) || srcW <= 0 || srcH <= 0) {
    throw new Error(`bad dimensions: ${srcW}x${srcH}`);
  }
  const scale = Math.min(1, maxDim / Math.max(srcW, srcH));
  return { w: Math.max(1, Math.round(srcW * scale)), h: Math.max(1, Math.round(srcH * scale)) };
}

/** Resolve "auto" to a concrete mime. PNG sources keep alpha via webp; photos go webp. */
export function resolveOutputMime(requested: OptimizeFormat, originalType: string): string {
  if (requested === "webp") return "image/webp";
  if (requested === "jpeg") return "image/jpeg";
  if (requested === "png") return "image/png";
  if (originalType === "image/png") return "image/webp";
  if (originalType.startsWith("image/")) return "image/webp";
  return "image/png";
}

export const MIME_FALLBACKS: Record<string, string[]> = {
  "image/webp": ["image/webp", "image/jpeg", "image/png"],
  "image/jpeg": ["image/jpeg", "image/png"],
  "image/png": ["image/png", "image/webp"],
};

function canvasToBlob(canvas: HTMLCanvasElement, mime: string, quality: number): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob((b) => resolve(b), mime, quality));
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("could not decode image (unsupported type?)"));
    img.src = url;
  });
}

export interface PreparedImage {
  bytes: Uint8Array;
  mime: string;
  w: number;
  h: number;
  srcW: number;
  srcH: number;
}

/** Downscale + transcode a File/Blob image. Throws on non-images or canvas failure. */
export async function prepareImage(source: Blob, originalType: string, opts: OptimizeOptions): Promise<PreparedImage> {
  const o = clampOptimize(opts);
  const url = URL.createObjectURL(source);
  try {
    const img = await loadImage(url);
    const srcW = img.naturalWidth;
    const srcH = img.naturalHeight;
    const { w, h } = computeTarget(srcW, srcH, o.maxDim);
    const primary = resolveOutputMime(o.format, originalType);
    const chain = MIME_FALLBACKS[primary] ?? [primary];
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("canvas 2d unavailable");
    ctx.imageSmoothingQuality = "high";
    // JPEG has no alpha: flatten onto white instead of black.
    if (chain[0] === "image/jpeg") {
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, w, h);
    }
    ctx.drawImage(img, 0, 0, w, h);
    for (const mime of chain) {
      const blob = await canvasToBlob(canvas, mime, o.quality);
      if (blob && blob.size > 0) {
        return { bytes: new Uint8Array(await blob.arrayBuffer()), mime, w, h, srcW, srcH };
      }
    }
    throw new Error("image transcode failed in this browser (tried webp/jpeg/png)");
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Fast dimension probe without full transcode. */
export async function probeDimensions(source: Blob): Promise<{ w: number; h: number }> {
  if (typeof createImageBitmap === "function") {
    try {
      const bmp = await createImageBitmap(source);
      const dims = { w: bmp.width, h: bmp.height };
      bmp.close();
      return dims;
    } catch {
      // fall through to <img> probe
    }
  }
  const url = URL.createObjectURL(source);
  try {
    const img = await loadImage(url);
    return { w: img.naturalWidth, h: img.naturalHeight };
  } finally {
    URL.revokeObjectURL(url);
  }
}
