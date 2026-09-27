export const MIN_HEIGHT = 160;

export type OverlayMaxHeightMode = 'suggestion' | 'action';

/**
 * オーバーレイの最大高さを画面サイズに応じて動的に計算する。
 * - **ウィンドウの現在高さ（innerHeight）ではなく画面サイズ（screen.availHeight）**を基準にする。
 *   （Electron の通知ウィンドウは初期高さが小さいため、innerHeight 基準だと常に上限が小さくなりがち）
 * - suggestion: 画面の 85% 程度（邪魔になりすぎない）
 * - action: 画面の 95% 程度（結果を読み切れるようにする）
 *
 * NOTE:
 * - 実際の「はみ出し禁止」は Electron(main) 側で workArea に収める（height クランプ + y 調整）ことで担保する。
 * - ここは renderer 側の「要求上限」。
 */
export const getMaxHeight = (mode: OverlayMaxHeightMode = 'suggestion'): number => {
  if (typeof window === 'undefined') return 520; // SSR fallback
  const availH = Number(window.screen?.availHeight || window.screen?.height || 0);
  const base = availH > 0 ? availH : 0;
  // suggestion は画面をほぼ使い切って読めることを優先（はみ出し禁止は main 側で担保）
  // action は「最大で全画面くらい」を許容する
  const ratio = mode === 'action' ? 1.0 : 0.95;
  const limit = base > 0 ? Math.floor(base * ratio) : 520;
  return Math.max(520, limit);
};

/** @deprecated 動的な getMaxHeight() を使用してください */
export const MAX_HEIGHT = 520;

/**
 * デザイン共通トークン
 * - 動的カラー（時間帯/ユーザ環境による軽微な最適化）
 * - メインウィンドウ内のモーダルではダークテキスト、overlay-window（通知）では白テキスト
 */
export const getAdaptiveColors = () => {
  const hour = new Date().getHours();
  const isDarkTime = hour < 7 || hour > 19;
  const isOverlayWindow =
    typeof document !== 'undefined' &&
    !!document.body &&
    document.body.classList.contains('overlay-window');

  return {
    primary: isDarkTime ? '#001A3D' : '#002B5B',
    text: isOverlayWindow ? 'rgba(255, 255, 255, 0.98)' : '#111827',
    border: isOverlayWindow ? 'rgba(255, 255, 255, 0.15)' : 'rgba(17, 24, 39, 0.12)',
    buttonText: isOverlayWindow ? 'rgba(255, 255, 255, 0.95)' : 'rgba(17, 24, 39, 0.95)',
    reducedMotion:
      typeof window !== 'undefined' &&
      window.matchMedia &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  } as const;
};

export const COLORS = getAdaptiveColors();

// Headerに関するstyledはHeaderBar.tsxへ移管済み
