const assert = require('node:assert/strict');
const test = require('node:test');

const { createOverlayActivationTracker } = require('../electron/overlay_activation_tracker');

test('overlay activation tracker treats active overlay interaction as recent', () => {
  let now = 1000;
  const tracker = createOverlayActivationTracker({ now: () => now });

  tracker.beginInteraction();
  now = 5000;

  assert.equal(tracker.hasRecentInteraction(now), true);

  tracker.endInteraction();
  now = 6000;

  assert.equal(tracker.hasRecentInteraction(now), false);
});
