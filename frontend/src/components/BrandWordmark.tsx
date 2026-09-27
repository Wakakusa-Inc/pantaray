export type BrandWordmarkProps = {
  className?: string;
};

/**
 * Pantaray のロゴ（シンボル＋ワードマーク）を表示する共通コンポーネント。
 *
 * 目的:
 * - ログイン画面を含む全画面で「Pantaray」表記を統一する
 * - ロゴ専用WebFontにより、OS/ブラウザ差による字形の揺れを抑える
 *
 * 注意:
 * - 文字列は必ず "Pantaray" で固定（翻訳しない）
 * - 視認性を損なう装飾（影/縁取り/グラデーション等）はCSSで禁止する方針
 */
export function BrandWordmark({ className }: BrandWordmarkProps) {
  const cls = ['brand-wordmark', className].filter(Boolean).join(' ');
  return (
    <div className={cls}>
      <span className="brand-wordmark-symbol" aria-hidden="true" />
      Pantaray
    </div>
  );
}
