const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { test } = require('node:test');

const { openNewWindowsInDefaultBrowser } = require('../electron/dist/security/windowOpenPolicy.js');

function openFromPage(url) {
  const app = new EventEmitter();
  const opened = [];
  openNewWindowsInDefaultBrowser({
    app,
    openExternal: async (target) => {
      opened.push(target);
    },
    logger: null,
  });
  let handler = null;
  app.emit('web-contents-created', {}, { setWindowOpenHandler: (fn) => (handler = fn) });
  return { result: handler({ url }), opened };
}

test('a web link from any page opens in the default browser, never in an app window', () => {
  const { result, opened } = openFromPage('https://example.com/docs');
  assert.deepEqual(result, { action: 'deny' });
  assert.deepEqual(opened, ['https://example.com/docs']);
});

test('a non-web link is neither opened externally nor in an app window', () => {
  for (const url of ['file:///etc/passwd', 'javascript:alert(1)', 'pantaray://auth', 'not a url']) {
    const { result, opened } = openFromPage(url);
    assert.deepEqual(result, { action: 'deny' });
    assert.deepEqual(opened, []);
  }
});
