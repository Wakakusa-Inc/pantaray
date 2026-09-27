const assert = require('node:assert/strict');
const { createCipheriv, createDecipheriv, randomBytes } = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test } = require('node:test');
const { createChatgptTokenStore } = require('../electron/dist/auth/chatgptTokenStore.js');
const {
  createEncryptedJsonFile,
  CredentialStorageError,
} = require('../electron/dist/auth/encryptedJsonFile.js');

const TOKENS = {
  accessToken: 'private-access-token',
  refreshToken: 'private-refresh-token',
  accountId: 'account-1',
  expiresAt: '2027-01-01T00:00:00.000Z',
};

function fixture(t) {
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'credential-storage-'));
  t.after(() => fs.rmSync(userDataDir, { recursive: true, force: true }));
  const key = randomBytes(32);
  // Node tests exercise the file boundary with authenticated encryption; real safeStorage is
  // verified by the desktop E2E when the settings controller is connected.
  const safeStorage = {
    isEncryptionAvailable: () => true,
    encryptString: (value) => {
      const iv = randomBytes(12);
      const cipher = createCipheriv('aes-256-gcm', key, iv);
      const encrypted = Buffer.concat([cipher.update(value, 'utf8'), cipher.final()]);
      return Buffer.concat([iv, cipher.getAuthTag(), encrypted]);
    },
    decryptString: (value) => {
      const decipher = createDecipheriv('aes-256-gcm', key, value.subarray(0, 12));
      decipher.setAuthTag(value.subarray(12, 28));
      return Buffer.concat([decipher.update(value.subarray(28)), decipher.final()]).toString(
        'utf8'
      );
    },
  };
  const storagePath = path.join(userDataDir, 'chatgpt-oauth.enc.json');
  const restart = () => createChatgptTokenStore({ userDataDir, safeStorage });
  return { userDataDir, storagePath, safeStorage, store: restart(), restart };
}

function assertStorageError(operation, code) {
  assert.throws(operation, (error) => {
    assert.ok(error instanceof CredentialStorageError);
    assert.equal(error.code, code);
    assert.equal(error.message.includes('private-'), false);
    return true;
  });
}

test('encrypted saves survive replacement and restart with private file permissions', (t) => {
  const f = fixture(t);
  assert.equal(f.store.load(), null);
  assert.deepEqual(f.store.save(TOKENS), { ok: true });
  const next = { ...TOKENS, refreshToken: 'private-new-refresh-token' };
  assert.deepEqual(f.store.save(next), { ok: true });
  assert.deepEqual(f.restart().load(), next);
  assert.equal(fs.statSync(f.storagePath).mode & 0o777, 0o600);
  assert.equal(fs.readFileSync(f.storagePath, 'utf8').includes('private-'), false);
  assert.deepEqual(fs.readdirSync(f.userDataDir), ['chatgpt-oauth.enc.json']);
});

test('lost encryption is an error for an existing file and cannot overwrite it', (t) => {
  const f = fixture(t);
  f.store.save(TOKENS);
  const before = fs.readFileSync(f.storagePath);
  f.safeStorage.isEncryptionAvailable = () => false;
  assertStorageError(() => f.restart().load(), 'encryption_unavailable');
  assert.equal(f.store.save({ ...TOKENS, accessToken: 'private-new' }).ok, false);
  assert.deepEqual(fs.readFileSync(f.storagePath), before);
  // Deleting the stored ciphertext does not need decryption.
  assert.deepEqual(f.store.clear(), { ok: true });
  assert.equal(f.restart().load(), null);
});

test('read permission failures are not mistaken for a missing credential', (t) => {
  const f = fixture(t);
  f.store.save(TOKENS);
  t.mock.method(fs, 'readFileSync', () => {
    throw Object.assign(new Error('private-read-error'), { code: 'EACCES' });
  });
  assertStorageError(() => f.store.load(), 'read_failed');
});

test('malformed envelopes, ciphertext and decoded token shapes report corruption', (t) => {
  const f = fixture(t);
  for (const raw of [
    '{"private-access-token":',
    JSON.stringify({ v: 1, ciphertext_b64: 'broken-ciphertext' }),
    JSON.stringify({ v: 2, ciphertext_b64: 'unknown-format' }),
  ]) {
    fs.writeFileSync(f.storagePath, raw);
    assertStorageError(() => f.store.load(), 'invalid_data');
    assert.equal(fs.readFileSync(f.storagePath, 'utf8'), raw);
  }
  for (const decoded of [null, { v: 1, tokens: { ...TOKENS, expiresAt: 'invalid' } }]) {
    fs.writeFileSync(
      f.storagePath,
      JSON.stringify({
        v: 1,
        ciphertext_b64: f.safeStorage.encryptString(JSON.stringify(decoded)).toString('base64'),
      })
    );
    assertStorageError(() => f.store.load(), 'invalid_data');
  }
});

test('a partial write preserves the previous credential and cleans its temporary file', (t) => {
  const f = fixture(t);
  f.store.save(TOKENS);
  const write = fs.writeFileSync;
  const fail = t.mock.method(fs, 'writeFileSync', (target) => {
    write(target, 'partial ciphertext');
    throw Object.assign(new Error('private-write-error'), { code: 'ENOSPC' });
  });
  assert.deepEqual(f.store.save({ ...TOKENS, accessToken: 'private-new' }), {
    ok: false,
    error: 'write_failed',
  });
  fail.mock.restore();
  assert.deepEqual(f.restart().load(), TOKENS);
  assert.deepEqual(fs.readdirSync(f.userDataDir), ['chatgpt-oauth.enc.json']);
});

test('a failed atomic replacement preserves the original credential', (t) => {
  const f = fixture(t);
  f.store.save(TOKENS);
  t.mock.method(fs, 'renameSync', () => {
    throw Object.assign(new Error('private-rename-error'), { code: 'EACCES' });
  });
  assert.equal(f.store.save({ ...TOKENS, accessToken: 'private-new' }).ok, false);
  assert.deepEqual(f.restart().load(), TOKENS);
  assert.deepEqual(fs.readdirSync(f.userDataDir), ['chatgpt-oauth.enc.json']);
});

test('deletion failure retains the saved credential and reports failure; a retry removes it', (t) => {
  const f = fixture(t);
  f.store.save(TOKENS);
  const fail = t.mock.method(fs, 'unlinkSync', () => {
    throw Object.assign(new Error('private-delete-error'), { code: 'EACCES' });
  });
  assert.deepEqual(f.store.clear(), {
    ok: false,
    error: 'delete_failed',
  });
  assert.deepEqual(f.restart().load(), TOKENS);
  fail.mock.restore();
  assert.deepEqual(f.store.clear(), { ok: true });
  assert.equal(f.restart().load(), null);
});

test('the file boundary sanitizes native encryption errors', (t) => {
  const f = fixture(t);
  const file = createEncryptedJsonFile(f.storagePath, f.safeStorage);
  f.safeStorage.encryptString = () => {
    throw new Error('private-encryption-error');
  };
  assertStorageError(() => file.write({ secret: 'private-key' }), 'write_failed');
  assert.deepEqual(fs.readdirSync(f.userDataDir), []);
});
