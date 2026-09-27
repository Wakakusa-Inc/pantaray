const assert = require('assert');
const { test } = require('node:test');

const {
  createActionApprovalModeFetcher,
  ActionApprovalModeResponseError,
} = require('../electron/dist/actions/actionApprovalModeFetch.js');

function createFetcher(respond) {
  const calls = [];
  const fetcher = createActionApprovalModeFetcher({
    getUserId: () => 'user-1',
    requestJson: async (request) => {
      calls.push(request);
      return respond(request);
    },
  });
  return { calls, fetcher };
}

test('action approval mode fetcher は action scope の canonical path を使う', async () => {
  const { calls, fetcher } = createFetcher(() => ({
    action_id: 'act-1',
    approval_mode: 'always_allow',
    source: 'action',
  }));

  const read = await fetcher.get('act-1');
  const written = await fetcher.update('act-1', 'always_allow');

  assert.deepStrictEqual(calls, [
    { path: '/v1/agents/users/user-1/actions/act-1/approval-mode', method: 'GET' },
    {
      path: '/v1/agents/users/user-1/actions/act-1/approval-mode',
      method: 'PUT',
      body: { approval_mode: 'always_allow' },
    },
  ]);
  assert.equal(read.source, 'action');
  assert.equal(written.approval_mode, 'always_allow');
});

test('action approval mode fetcher は別 action の応答を拒否する', async () => {
  const { fetcher } = createFetcher(() => ({
    action_id: 'act-other',
    approval_mode: 'always_allow',
    source: 'action',
  }));

  await assert.rejects(() => fetcher.get('act-1'), ActionApprovalModeResponseError);
});
