const assert = require('assert');
const { test } = require('node:test');

const {
  createApprovalPreferenceFetcher,
} = require('../electron/dist/settings/approvalPreferencesFetch.js');

test('approval preference fetcher は canonical response を受け入れる', async () => {
  /** @type {Array<unknown>} */
  const calls = [];
  const fetcher = createApprovalPreferenceFetcher({
    getUserId: () => 'user-1',
    requestJson: async (request) => {
      calls.push(request);
      return {
        scope_type: 'global',
        scope_ref: null,
        approval_mode: 'always_allow',
        applies_to: ['workspace_edit_and_command'],
      };
    },
  });

  const response = await fetcher.get();

  assert.equal(calls.length, 1);
  assert.deepStrictEqual(calls[0], {
    path: '/v1/agents/users/user-1/approval-preferences/workspace-edit-and-command',
    method: 'GET',
  });
  assert.equal(response.approval_mode, 'always_allow');
});

test('approval preference fetcher は canonical payload で更新する', async () => {
  /** @type {Array<unknown>} */
  const calls = [];
  const fetcher = createApprovalPreferenceFetcher({
    getUserId: () => 'user-1',
    requestJson: async (request) => {
      calls.push(request);
      return {
        scope_type: 'global',
        scope_ref: null,
        approval_mode: 'always_allow',
        applies_to: ['workspace_edit_and_command'],
      };
    },
  });

  const response = await fetcher.update('always_allow');

  assert.equal(calls.length, 1);
  assert.deepStrictEqual(calls[0], {
    path: '/v1/agents/users/user-1/approval-preferences/workspace-edit-and-command',
    method: 'PUT',
    body: { approval_mode: 'always_allow' },
  });
  assert.equal(response.approval_mode, 'always_allow');
});
