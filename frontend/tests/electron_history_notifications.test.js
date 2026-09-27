const assert = require('node:assert/strict');
const { test } = require('node:test');
const { broadcastHistoryChanged } = require('../electron/dist/orchestration/historyNotifications.js');

test('read receipt と実行更新の refresh を同じ履歴通知として送る', () => {
  const received = [];
  const mainWindow = {
    isDestroyed: () => false,
    webContents: { send: (...message) => received.push(message) },
  };
  const receipt = { source: 'read_state' };
  const completion = { source: 'orchestration_event', event: 'process_completed' };
  broadcastHistoryChanged(mainWindow, receipt);
  broadcastHistoryChanged(mainWindow, completion);
  assert.deepEqual(received, [['history:changed', receipt], ['history:changed', completion]]);
});

test('renderer への送信失敗は保存済みの操作へ伝播せず、private 内容をログに出さない', (t) => {
  const warnings = [];
  t.mock.method(console, 'warn', (...args) => warnings.push(args));
  const mainWindow = {
    isDestroyed: () => false,
    webContents: { send: () => { throw new Error('private renderer detail'); } },
  };
  assert.doesNotThrow(() => broadcastHistoryChanged(mainWindow, { source: 'read_state' }));
  assert.equal(warnings.length, 1);
  assert.equal(JSON.stringify(warnings).includes('private renderer detail'), false);
});
