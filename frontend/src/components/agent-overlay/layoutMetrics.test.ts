import { describe, expect, it } from 'vitest';
import { getCollapsedPreviewHeightPx, shouldExpandScrollableContent } from './layoutMetrics';

describe('layoutMetrics', () => {
  it('calculates the collapsed preview height from the scroll container font size', () => {
    expect(getCollapsedPreviewHeightPx(16)).toBeCloseTo(63.2);
  });

  it('expands only when full content exceeds the collapsed preview threshold', () => {
    expect(
      shouldExpandScrollableContent({
        contentHeightPx: 84,
        collapsedPreviewHeightPx: 80,
        thresholdPx: 4,
      })
    ).toBe(false);

    expect(
      shouldExpandScrollableContent({
        contentHeightPx: 85,
        collapsedPreviewHeightPx: 80,
        thresholdPx: 4,
      })
    ).toBe(true);
  });
});
