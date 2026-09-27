export type ShareCardNativeImage = {
  getSize: (scaleFactor?: number) => { width: number; height: number };
  resize: (options: { width: number; height: number; quality: 'best' }) => ShareCardNativeImage;
  toPNG: () => Uint8Array;
};

export type ShareCardNativeImageFactory = {
  createFromBuffer: (buffer: Buffer) => ShareCardNativeImage;
};

export type ShareCardCapturePlan = {
  totalHeight: number;
  viewportHeight: number;
  segments: Array<{ offset: number; visibleHeight: number }>;
};

const TARGET_WIDTH_PX = 1600;
const MAX_OUTPUT_AREA_PX = 110_000_000;
const MIN_CAPTURE_HEIGHT_PX = 120;
const MAX_CAPTURE_HEIGHT_PX = 200_000;
const CAPTURE_VIEWPORT_HEIGHT_PX = 1200;

function clamp(n: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, n));
}

export function computeResize({ width, height }: { width: number; height: number }): {
  width: number;
  height: number;
} {
  let w = Math.max(1, Math.floor(width));
  let h = Math.max(1, Math.floor(height));

  if (w !== TARGET_WIDTH_PX) {
    const s = TARGET_WIDTH_PX / w;
    w = TARGET_WIDTH_PX;
    h = Math.max(1, Math.round(h * s));
  }

  const area = w * h;
  if (area > MAX_OUTPUT_AREA_PX) {
    const s = Math.sqrt(MAX_OUTPUT_AREA_PX / area);
    w = Math.max(1, Math.floor(w * s));
    h = Math.max(1, Math.floor(h * s));
  }

  return { width: w, height: h };
}

export function computeCaptureWindowHeight(measuredHeight: number): number {
  return clamp(Math.ceil(measuredHeight), MIN_CAPTURE_HEIGHT_PX, MAX_CAPTURE_HEIGHT_PX);
}

export function computeShareCardCapturePlan(measuredHeight: number): ShareCardCapturePlan {
  const totalHeight = computeCaptureWindowHeight(measuredHeight);
  const viewportHeight = Math.min(totalHeight, CAPTURE_VIEWPORT_HEIGHT_PX);
  const segments: ShareCardCapturePlan['segments'] = [];

  for (let offset = 0; offset < totalHeight; offset += viewportHeight) {
    segments.push({
      offset,
      visibleHeight: Math.min(viewportHeight, totalHeight - offset),
    });
  }

  return { totalHeight, viewportHeight, segments };
}
