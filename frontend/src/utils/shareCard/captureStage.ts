/**
 * AgentOverlay の共有スクリーンショット用に、画面外（offscreen）へ「キャプチャ専用ステージ」を生成する。
 *
 * 目的:
 * - 表示中のOverlayウィンドウは520pxのまま維持
 * - 共有画像は常に「全文」（スクロール解除）を1枚に入れる
 * - UI操作部品（ボタン類）を写り込ませない
 *
 * 実装方針:
 * - `cloneNode(true)` でDOMを複製し、`position: fixed` で画面外に配置
 * - CSS override（inline + computed style heuristics）で scroll/transform/opacity を補正
 * - フォント/レイアウト安定のため、2フレーム待機 + `document.fonts.ready` を可能な範囲で待つ
 */
export type ShareCardCaptureStage = {
  /** 画面外に挿入されたステージ要素 */
  stageEl: HTMLDivElement;
  /** キャプチャ対象（cloneしたOverlayルート） */
  captureEl: HTMLElement;
  /** 後片付け（DOM除去） */
  cleanup: () => void;
};

const STAGE_ID = 'pantaray-sharecard-capture-stage';

type CreateStageParams = {
  /**
   * キャプチャ元のOverlayコンテナ（`PopupContainer` 相当）。
   * - 例: `useAgentOverlayController` の `containerRef.current`
   */
  sourceEl: HTMLElement;
};

function removeExistingStage(): void {
  try {
    document.getElementById(STAGE_ID)?.remove();
  } catch {
    // no-op
  }
}

function nextAnimationFrame(): Promise<void> {
  return new Promise((resolve) => {
    if (typeof window === 'undefined' || typeof window.requestAnimationFrame !== 'function') {
      setTimeout(() => resolve(), 0);
      return;
    }
    window.requestAnimationFrame(() => resolve());
  });
}

async function waitForFontsReady(): Promise<void> {
  try {
    // `document.fonts` は Electron/Chromium では概ね利用可能だが、存在しない環境も想定して fail-safe。
    const fonts = document.fonts;
    if (!fonts?.ready) return;
    await fonts.ready;
  } catch {
    // no-op
  }
}

function forceScrollableToExpand(el: HTMLElement): void {
  // 「全文」にするため scroll を解除し、高さ制約を消す
  el.style.maxHeight = 'none';
  el.style.overflow = 'visible';
  el.style.overflowY = 'visible';
  el.style.height = 'auto';
  el.style.flexGrow = '0';
  el.style.paddingRight = '0';
}

function isLikelyScrollable(el: HTMLElement): boolean {
  try {
    const st = window.getComputedStyle(el);
    const overflowY = st.overflowY;
    const maxH = st.maxHeight;
    if (overflowY === 'auto' || overflowY === 'scroll') return true;
    if (maxH && maxH !== 'none' && maxH !== '0px') return true;
    return false;
  } catch {
    return false;
  }
}

function hideHeaderAndFooter(root: HTMLElement): void {
  // 明示指定（将来的にdata属性を付けた場合）
  root.querySelectorAll<HTMLElement>('[data-sharecard-hide="true"]').forEach((el) => {
    el.style.display = 'none';
  });

  // fallback: HeaderRow は `-webkit-app-region: drag` を持つため、それを目印に非表示
  root.querySelectorAll<HTMLElement>('*').forEach((el) => {
    try {
      const region = window.getComputedStyle(el).getPropertyValue('-webkit-app-region');
      if (region === 'drag') {
        el.style.display = 'none';
      }
    } catch {
      // no-op
    }
  });

  // fallback: Footer は `margin-top: auto` で下寄せされるので、それを目印に非表示
  root.querySelectorAll<HTMLElement>('*').forEach((el) => {
    try {
      const st = window.getComputedStyle(el);
      if (st.marginTop === 'auto') {
        // ボタン群を含むケースが多いのでガード
        if (el.querySelector('button')) {
          el.style.display = 'none';
        }
      }
    } catch {
      // no-op
    }
  });

  // 最終fallback: 操作系を丸ごと消す（Markdown内にbuttonが出る想定は薄い）
  root.querySelectorAll<HTMLButtonElement>('button').forEach((btn) => {
    btn.style.display = 'none';
  });
}

function disableAnimations(root: HTMLElement): void {
  // 共有画像で揺れ/途中状態を避けるため、基本は全要素でtransition/animationを潰す
  root.querySelectorAll<HTMLElement>('*').forEach((el) => {
    el.style.animation = 'none';
    el.style.transition = 'none';
  });
}

function forceVisible(root: HTMLElement): void {
  root.querySelectorAll<HTMLElement>('[data-sharecard-force-visible="true"]').forEach((el) => {
    el.style.opacity = '1';
  });
}

function normalizeRootLayout(root: HTMLElement, widthPx: number): void {
  // `PopupContainer` は通常 `height: 100%` だが、ステージでは内容で伸ばしたい
  root.style.width = `${widthPx}px`;
  root.style.height = 'auto';
  root.style.opacity = '1';
  root.style.transform = 'none';
  root.style.transition = 'none';
  root.style.willChange = 'auto';
  // 丸角はhtml2canvasでギザギザになるため、compose.ts側で滑らかなマスクを適用する
  root.style.borderRadius = '0';
}

function expandAllScrollables(root: HTMLElement): void {
  const explicit = Array.from(root.querySelectorAll<HTMLElement>('[data-sharecard-scroll="true"]'));
  if (explicit.length > 0) {
    explicit.forEach(forceScrollableToExpand);
    return;
  }

  // fallback: computed styleでscroll要素っぽいものを探して解除
  const candidates = Array.from(root.querySelectorAll<HTMLElement>('*')).filter(isLikelyScrollable);
  candidates.forEach(forceScrollableToExpand);
}

function applyShareCardOverrides(root: HTMLElement, widthPx: number): void {
  normalizeRootLayout(root, widthPx);
  disableAnimations(root);
  hideHeaderAndFooter(root);
  forceVisible(root);
  expandAllScrollables(root);
}

/**
 * 画面外に共有スクリーンショット用のステージを作り、全文がレンダリングされたDOMを返す。
 */
export async function createShareCardCaptureStage(
  params: CreateStageParams
): Promise<ShareCardCaptureStage> {
  removeExistingStage();

  const rect = params.sourceEl.getBoundingClientRect();
  const widthPx = Math.max(1, Math.ceil(rect.width));

  const stageEl = document.createElement('div');
  stageEl.id = STAGE_ID;
  stageEl.setAttribute('aria-hidden', 'true');
  stageEl.style.position = 'fixed';
  stageEl.style.left = '-10000px';
  stageEl.style.top = '0';
  stageEl.style.width = `${widthPx}px`;
  stageEl.style.pointerEvents = 'none';
  stageEl.style.background = 'transparent';
  stageEl.style.contain = 'layout style paint';

  const captureEl = params.sourceEl.cloneNode(true) as HTMLElement;
  captureEl.style.width = '100%';

  stageEl.appendChild(captureEl);
  document.body.appendChild(stageEl);

  // style override はDOMに挿入してから適用（computed styleが安定する）
  applyShareCardOverrides(captureEl, widthPx);

  // レイアウト安定待ち
  await waitForFontsReady();
  await nextAnimationFrame();
  await nextAnimationFrame();

  // 再度 scroll解除を適用（内容量が増えた後に max-height が効くケースがあるため）
  expandAllScrollables(captureEl);

  const cleanup = () => {
    try {
      stageEl.remove();
    } catch {
      // no-op
    }
  };

  return { stageEl, captureEl, cleanup };
}
