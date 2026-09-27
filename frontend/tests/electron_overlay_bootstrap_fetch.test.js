const assert = require('assert');
const { test } = require('node:test');

const {
  createOverlayBootstrapFetcher,
} = require('../electron/dist/history/overlayBootstrapFetch.js');

test('overlay bootstrap fetcher は shared local backend client へ path を委譲する', async () => {
  /** @type {Array<unknown>} */
  const calls = [];
  const fetchOverlayBootstrap = createOverlayBootstrapFetcher({
    requestJson: async (request) => {
      calls.push(request);
      return {
        suggestion_id: 'sug-1',
        snapshot: { suggestionId: 'sug-1', processId: null, actionId: null },
        last_sequence: 7,
        live_resume: {
          kind: 'action',
          process_id: 'proc-1',
          action_id: 'act-1',
          command_id: 'cmd-1',
          accepted_at: '2026-03-23T00:00:00Z',
        },
      };
    },
  });

  const result = await fetchOverlayBootstrap('sug-1');

  assert.equal(calls.length, 1);
  assert.deepStrictEqual(calls[0], {
    path: '/api/agent/history/sug-1/overlay-bootstrap',
    method: 'GET',
  });
  assert.equal(result.suggestionId, 'sug-1');
  assert.equal(result.liveResume.kind, 'action');
  assert.equal(result.liveResume.processId, 'proc-1');
});
