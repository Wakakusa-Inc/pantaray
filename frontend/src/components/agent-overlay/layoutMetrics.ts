export const COLLAPSED_PREVIEW_EM = 3.2;
export const COLLAPSED_PREVIEW_EXTRA_PX = 12;
export const COLLAPSED_PREVIEW_MAX_HEIGHT_CSS = `calc(${COLLAPSED_PREVIEW_EM}em + ${COLLAPSED_PREVIEW_EXTRA_PX}px)`;

export type ScrollableExpansionMetrics = {
  contentHeightPx: number;
  collapsedPreviewHeightPx: number;
  thresholdPx: number;
};

export function getCollapsedPreviewHeightPx(fontSizePx: number): number {
  if (!Number.isFinite(fontSizePx) || fontSizePx <= 0) {
    return COLLAPSED_PREVIEW_EXTRA_PX;
  }
  return fontSizePx * COLLAPSED_PREVIEW_EM + COLLAPSED_PREVIEW_EXTRA_PX;
}

export function shouldExpandScrollableContent({
  contentHeightPx,
  collapsedPreviewHeightPx,
  thresholdPx,
}: ScrollableExpansionMetrics): boolean {
  if (contentHeightPx <= 0 || collapsedPreviewHeightPx <= 0) {
    return false;
  }
  return contentHeightPx > collapsedPreviewHeightPx + thresholdPx;
}
