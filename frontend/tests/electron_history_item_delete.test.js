const assert = require('node:assert/strict');
const { test } = require('node:test');

const { LocalBackendRequestError } = require('../electron/dist/localBackend/client.js');
const { createHistoryItemDeleter } = require('../electron/dist/history/historyItemDelete.js');

test('削除できたら会話の画面を閉じ、id は path の一区切りに収める', async () => {
  const requests = [];
  const closed = [];
  const deleteItem = createHistoryItemDeleter({
    requestJson: async (request) => {
      requests.push(request);
      return undefined;
    },
    closeConversationWindow: (request) => closed.push(request),
  });

  assert.deepEqual(await deleteItem({ kind: 'suggestion', id: 'a/b?c' }), { ok: true });
  assert.equal(requests[0].path, '/api/agent/history/items/suggestion/a%2Fb%3Fc');
  assert.equal(requests[0].method, 'DELETE');
  assert.deepEqual(closed, [{ kind: 'suggestion', id: 'a/b?c' }]);
});

test('実行中の 409 はエラーコードを返し、会話の画面を閉じない', async () => {
  const closed = [];
  const deleteItem = createHistoryItemDeleter({
    requestJson: async () => {
      throw new LocalBackendRequestError('Conversation is in use', 409, 'CONVERSATION_BUSY');
    },
    closeConversationWindow: (request) => closed.push(request),
  });

  assert.deepEqual(await deleteItem({ kind: 'conversation', id: 'action-1' }), {
    ok: false,
    errorCode: 'CONVERSATION_BUSY',
  });
  assert.deepEqual(closed, []);
});
