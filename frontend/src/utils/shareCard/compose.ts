import html2canvas from 'html2canvas';

export type ShareCardPngResult = {
  /** PNG Blob（renderer内のコピー/保存に使用） */
  blob: Blob;
  /** PNG bytes（IPC経由でmainへ渡してDownloads保存する用） */
  bytes: Uint8Array;
  /** 出力画像のピクセルサイズ */
  width: number;
  height: number;
};

type RenderShareCardParams = {
  /** キャプチャ対象（スクロール解除済みのOverlayルート） */
  captureEl: HTMLElement;
};

// NOTE:
// - 出力は通常のRetina（2x）密度に合わせる。これにより画像サイズが自然になる。
// - キャプチャは3xでスーパーサンプリングし、2xにダウンサンプルすることで文字を滑らかに。
// - 長文の全文キャプチャは縦が伸びるため、面積上限で落とす（DoS/メモリ破綻対策）。
const MAX_OUTPUT_AREA_PX = 110_000_000; // 110MP（メモリ/速度の安全域）
// "スーパーサンプリング"は逆にボケの原因になることがあるため、出力等倍(2x)で素直に撮る
const CAPTURE_SCALE_MAX = 2;
// 出力は通常のRetina密度（2x）に合わせる（自然な画像サイズ）
const OUTPUT_DENSITY = 2;

function clamp(n: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, n));
}

function computeCaptureScale(captureEl: HTMLElement): number {
  const rect = captureEl.getBoundingClientRect();
  const areaAtScale1 = Math.max(1, rect.width) * Math.max(1, rect.height);
  const limit = Math.sqrt(MAX_OUTPUT_AREA_PX / areaAtScale1);
  // NOTE:
  // - キャプチャは出力と同じ2xで行う（変な縮小補間を避けてシャープさを保つ）
  // - ただし面積上限（limit）で落とす
  const preferred = CAPTURE_SCALE_MAX; // 2x
  const decided = Math.min(preferred, limit, CAPTURE_SCALE_MAX);
  return clamp(Math.floor(decided * 100) / 100, 1, CAPTURE_SCALE_MAX);
}

function computeOutputScale(cssW: number, cssH: number, captureScale: number): number {
  const areaCss = Math.max(1, cssW) * Math.max(1, cssH);
  const limit = Math.sqrt(MAX_OUTPUT_AREA_PX / areaCss);
  // 出力は 2x（Retina密度）を基本にしつつ、面積上限とキャプチャscaleを超えない
  const desired = OUTPUT_DENSITY;
  return clamp(Math.floor(Math.min(desired, limit, captureScale) * 100) / 100, 1, desired);
}

function drawAccentBackground(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  // ベース（明るめにしてOverlayとのコントラストを稼ぐ）
  const baseGrad = ctx.createLinearGradient(0, 0, 0, h);
  baseGrad.addColorStop(0, '#c3cfe2'); // 明るいシルバーブルー
  baseGrad.addColorStop(1, '#a1bafe'); // 鮮やかなペールブルー
  ctx.fillStyle = baseGrad;
  ctx.fillRect(0, 0, w, h);

  // Mist（薄い膜）: 上からうっすら白を足す
  {
    const prev = ctx.globalCompositeOperation;
    ctx.globalCompositeOperation = 'screen';
    const mist = ctx.createRadialGradient(
      w * 0.45,
      h * -0.1,
      0,
      w * 0.45,
      h * -0.1,
      Math.max(w, h) * 0.9
    );
    mist.addColorStop(0, 'rgba(255, 255, 255, 0.4)');
    mist.addColorStop(1, 'rgba(255, 255, 255, 0)');
    ctx.fillStyle = mist;
    ctx.fillRect(0, 0, w, h);
    ctx.globalCompositeOperation = prev;
  }

  // アクセント: cyanの淡いラジアル（screenで爽やかに）
  const prevOp = ctx.globalCompositeOperation;
  ctx.globalCompositeOperation = 'screen';

  const g1 = ctx.createRadialGradient(0, 0, 0, w * 0.25, h * 0.22, w * 0.85);
  g1.addColorStop(0, 'rgba(120, 255, 255, 0.5)'); // より明るく
  g1.addColorStop(1, 'rgba(120, 255, 255, 0)');
  ctx.fillStyle = g1;
  ctx.fillRect(0, 0, w, h);

  ctx.globalCompositeOperation = prevOp;
}

function roundedRectPath(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number
): void {
  const rr = Math.max(0, Math.min(r, Math.min(w, h) / 2));
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.lineTo(x + w - rr, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + rr);
  ctx.lineTo(x + w, y + h - rr);
  ctx.quadraticCurveTo(x + w, y + h, x + w - rr, y + h);
  ctx.lineTo(x + rr, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - rr);
  ctx.lineTo(x, y + rr);
  ctx.quadraticCurveTo(x, y, x + rr, y);
  ctx.closePath();
}

function drawDerivedBlurBackground(
  ctx: CanvasRenderingContext2D,
  overlayCanvas: HTMLCanvasElement,
  x: number,
  y: number,
  w: number,
  h: number
): void {
  // Overlay自体の雰囲気（LiquidGlass/背景）を安定して写すための派生背景
  // - 背景側に薄く敷いて、外部背景が一切写らないようにする
  const scale = 1.12;
  const dw = overlayCanvas.width * scale;
  const dh = overlayCanvas.height * scale;
  const dx = x - (dw - overlayCanvas.width) / 2;
  const dy = y - (dh - overlayCanvas.height) / 2;

  // NOTE: w/h は将来の追加調整（ビネット/マスク等）用に受けている
  void w;
  void h;

  const prevAlpha = ctx.globalAlpha;
  const prevFilter = ctx.filter;
  const prevOp = ctx.globalCompositeOperation;

  // “濁り”を避けるため、強すぎるブラー/ビネットは抑える
  ctx.globalCompositeOperation = 'screen';
  ctx.globalAlpha = 0.1;
  ctx.filter = 'blur(30px) saturate(116%) contrast(103%)';
  ctx.drawImage(overlayCanvas, dx, dy, dw, dh);

  ctx.globalAlpha = prevAlpha;
  ctx.filter = prevFilter;
  ctx.globalCompositeOperation = prevOp;
}

async function canvasToPngBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  const blob = await new Promise<Blob | null>((resolve) => {
    canvas.toBlob((b) => resolve(b), 'image/png');
  });
  if (!blob) {
    throw new Error('PNGの生成に失敗しました。');
  }
  return blob;
}

/**
 * スクロール解除済みのOverlay DOMをキャプチャし、Pantaray風の背景で合成した「共有カードPNG」を生成する。
 */
export async function renderShareCardPng(
  params: RenderShareCardParams
): Promise<ShareCardPngResult> {
  const captureScale = computeCaptureScale(params.captureEl);

  // 1) Overlay自体をキャプチャ（背景透過）
  const overlayCanvas = await html2canvas(params.captureEl, {
    backgroundColor: null,
    scale: captureScale,
    useCORS: true,
    allowTaint: true,
    logging: false,
    imageTimeout: 0, // 画像の読み込みを待つ
    // NOTE:
    // - foreignObjectRendering は Electron/環境差で「テキストが描けない」ケースがあるため使用しない
    // - 文字の粗さは scale 側で稼ぐ（3x出力 + 4xキャプチャからのスーパーサンプリング）
  });

  // 2) 出力スケール（基本2x）。キャプチャ画像から“スーパーサンプリング”でダウンサンプルして文字のギザギザを抑える。
  const cssW = Math.max(1, overlayCanvas.width / captureScale);
  const cssH = Math.max(1, overlayCanvas.height / captureScale);
  const outputScale = computeOutputScale(cssW, cssH, captureScale);

  const normalizedOverlay = document.createElement('canvas');
  normalizedOverlay.width = Math.max(1, Math.round(cssW * outputScale));
  normalizedOverlay.height = Math.max(1, Math.round(cssH * outputScale));
  const nctx = normalizedOverlay.getContext('2d');
  if (!nctx) throw new Error('Canvasコンテキストの取得に失敗しました。');
  nctx.imageSmoothingEnabled = true;
  nctx.imageSmoothingQuality = 'high';
  nctx.drawImage(overlayCanvas, 0, 0, normalizedOverlay.width, normalizedOverlay.height);

  // 3) 余白はCSS px基準で決め、出力ピクセルでは outputScale を掛ける（見た目の余白量を一定に）
  const padCss = clamp(Math.round(cssW * 0.055), 30, 68);
  const padPx = Math.round(padCss * outputScale);
  const outW = normalizedOverlay.width + padPx * 2;
  const outH = normalizedOverlay.height + padPx * 2;

  // 4) 合成用キャンバス
  const outCanvas = document.createElement('canvas');
  outCanvas.width = outW;
  outCanvas.height = outH;
  const ctx = outCanvas.getContext('2d');
  if (!ctx) {
    throw new Error('Canvasコンテキストの取得に失敗しました。');
  }

  drawAccentBackground(ctx, outW, outH);
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'high';
  drawDerivedBlurBackground(ctx, normalizedOverlay, padPx, padPx, outW, outH);

  // 5) Overlay配置
  const cardX = padPx;
  const cardY = padPx;
  const cardW = normalizedOverlay.width;
  const cardH = normalizedOverlay.height;
  const radius = Math.round(16 * outputScale); // PopupContainerに合わせる（出力密度に追従）

  // 5-a) 多層シャドウ（自然なソフトシャドウ）
  // 遠い影（ぼんやり・広範囲）
  ctx.save();
  ctx.filter = 'blur(48px)';
  ctx.globalAlpha = 0.22;
  ctx.fillStyle = '#000';
  roundedRectPath(ctx, cardX, cardY + Math.round(16 * outputScale), cardW, cardH, radius);
  ctx.fill();
  ctx.restore();
  // 近い影（くっきり・接地感）
  ctx.save();
  ctx.filter = 'blur(16px)';
  ctx.globalAlpha = 0.28;
  ctx.fillStyle = '#000';
  roundedRectPath(ctx, cardX, cardY + Math.round(8 * outputScale), cardW, cardH, radius);
  ctx.fill();
  ctx.restore();

  // 5-b) Overlayに滑らかな丸角マスクを適用して配置
  // html2canvasの丸角はギザギザになるため、compose側でCanvas 2Dの滑らかなマスクを適用する
  const maskedOverlay = document.createElement('canvas');
  maskedOverlay.width = cardW;
  maskedOverlay.height = cardH;
  const mctx = maskedOverlay.getContext('2d');
  if (mctx) {
    mctx.imageSmoothingEnabled = true;
    mctx.imageSmoothingQuality = 'high';

    // 丸角マスクを先に描く（Canvas 2Dのパス描画はアンチエイリアスが効く）
    // 少し内側に描いて、エッジのソフトネスを稼ぐ
    const feather = Math.max(0.5, outputScale * 0.3); // 微細なフェザー
    mctx.fillStyle = '#fff';
    roundedRectPath(
      mctx,
      feather,
      feather,
      cardW - feather * 2,
      cardH - feather * 2,
      Math.max(0, radius - feather)
    );
    mctx.fill();

    // source-in: マスク部分にのみOverlayを描画
    mctx.globalCompositeOperation = 'source-in';
    mctx.drawImage(normalizedOverlay, 0, 0);
    mctx.globalCompositeOperation = 'source-over';
  }
  ctx.drawImage(maskedOverlay, cardX, cardY);

  const blob = await canvasToPngBlob(outCanvas);
  const bytes = new Uint8Array(await blob.arrayBuffer());

  return { blob, bytes, width: outW, height: outH };
}
