const assert = require('assert');
const { test } = require('node:test');

const {
  parseLoopbackBackendUrl,
  resolveLoopbackBinding,
} = require('../electron/loopback_backend_url.js');

test('loopback backend URL accepts only an explicit local HTTP origin', () => {
  assert.equal(parseLoopbackBackendUrl('http://127.0.0.1:8005').origin, 'http://127.0.0.1:8005');
  assert.deepEqual(resolveLoopbackBinding('http://localhost:49152'), {
    appPort: 49152,
    bindHost: '127.0.0.1',
    bindPort: 49152,
  });
});

for (const invalidUrl of [
  'https://127.0.0.1:8005',
  'http://example.test:8005',
  'http://127.0.0.1',
  'http://127.0.0.1:0',
  'http://user:password@127.0.0.1:8005',
  'http://127.0.0.1:8005/api',
  'http://127.0.0.1:8005/?token=secret',
  'http://127.0.0.1:8005/#fragment',
]) {
  test(`loopback backend URL rejects ${invalidUrl}`, () => {
    assert.throws(() => parseLoopbackBackendUrl(invalidUrl));
  });
}
