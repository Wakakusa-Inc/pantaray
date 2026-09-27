const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { test } = require('node:test');

const { AuthAttemptStore } = require('../electron/auth_attempt_store');

function createTempDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'pantaray-electron-test-'));
}

function createSafeStorageStub() {
  return {
    isEncryptionAvailable: () => true,
    encryptString: (plain) => {
      const buf = Buffer.from(String(plain), 'utf8');
      for (let i = 0; i < buf.length; i += 1) {
        buf[i] = buf[i] ^ 0xaa;
      }
      return buf;
    },
    decryptString: (buf) => {
      const b = Buffer.from(buf);
      for (let i = 0; i < b.length; i += 1) {
        b[i] = b[i] ^ 0xaa;
      }
      return b.toString('utf8');
    },
  };
}

test('AuthAttemptStore: get() peeks verifier without consuming, consume() removes it', () => {
  const dir = createTempDir();
  const safeStorage = createSafeStorageStub();

  const store1 = new AuthAttemptStore({ userDataDir: dir, safeStorage, ttlMs: 10 * 60 * 1000, logger: console });
  store1.put('A1', 'V1');

  assert.equal(store1.get('A1'), 'V1');
  assert.equal(store1.get('A1'), 'V1'); // still present

  // Reload from disk to ensure persistence works with peek
  const store2 = new AuthAttemptStore({ userDataDir: dir, safeStorage, ttlMs: 10 * 60 * 1000, logger: console });
  assert.equal(store2.get('A1'), 'V1');

  assert.equal(store2.consume('A1'), 'V1');
  assert.equal(store2.get('A1'), null);
});

