const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test } = require('node:test');
const {
  ApiKeyProviderSchema,
  ConnectionPreferencesSchema,
  EMPTY_CONNECTION_PREFERENCES,
} = require('../electron/dist/aiConnection/preferences.js');
const { createConnectionSettingsStore } = require('../electron/dist/aiConnection/settingsStore.js');
const { CredentialStorageError } = require('../electron/dist/auth/encryptedJsonFile.js');

function fixture(t) {
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'connection-settings-'));
  t.after(() => fs.rmSync(userDataDir, { recursive: true, force: true }));
  // Encryption/file failure coverage lives in electron_credential_storage.test.js.
  const safeStorage = {
    isEncryptionAvailable: () => true,
    encryptString: (value) => Buffer.from(value.split('').reverse().join('')),
    decryptString: (value) => value.toString().split('').reverse().join(''),
  };
  const restart = () => createConnectionSettingsStore({ userDataDir, safeStorage });
  return { userDataDir, safeStorage, store: restart(), restart };
}

test('an empty profile does not manufacture a configured connection', (t) => {
  const { store } = fixture(t);
  assert.deepEqual(store.readPreferences(), EMPTY_CONNECTION_PREFERENCES);
  assert.equal(store.readApiKey('openai'), null);
  assert.equal(store.readWebSearchKey(), null);
});

test('provider keys, direct selection, model and search key survive restart independently', (t) => {
  const f = fixture(t);
  for (const provider of ApiKeyProviderSchema.options)
    f.store.saveApiKey(provider, `key-${provider}`);
  f.store.saveWebSearchKey('tvly-key');
  const preferences = {
    method: 'chatgpt',
    provider: 'fireworks',
    model: 'custom-model',
  };
  f.store.savePreferences(preferences);
  const restored = f.restart();
  assert.deepEqual(restored.readPreferences(), preferences);
  for (const provider of ApiKeyProviderSchema.options)
    assert.equal(restored.readApiKey(provider), `key-${provider}`);
  assert.equal(restored.readWebSearchKey(), 'tvly-key');
  restored.removeApiKey('openai');
  restored.removeWebSearchKey();
  assert.equal(f.restart().readApiKey('openai'), null);
  assert.equal(f.restart().readWebSearchKey(), null);
  assert.equal(f.restart().readApiKey('anthropic'), 'key-anthropic');
  assert.deepEqual(f.restart().readPreferences(), preferences);
});

test('a saved Codex Luna selection remains the selected model after restart', (t) => {
  const f = fixture(t);
  f.store.savePreferences({ method: 'chatgpt', provider: 'openai', model: 'gpt-5.6-luna' });

  assert.equal(f.restart().readPreferences().model, 'gpt-5.6-luna');
  const envelope = JSON.parse(
    fs.readFileSync(path.join(f.userDataDir, 'ai-connection-preferences.enc.json'), 'utf8')
  );
  const persisted = JSON.parse(
    f.safeStorage.decryptString(Buffer.from(envelope.ciphertext_b64, 'base64'))
  );
  assert.equal(persisted.model, 'gpt-5.6-luna');
  assert.equal(f.restart().readPreferences().model, 'gpt-5.6-luna');
});

test('a credential file copied to another provider is rejected instead of sent there', (t) => {
  const f = fixture(t);
  f.store.saveApiKey('openai', 'key-openai');
  fs.copyFileSync(
    path.join(f.userDataDir, 'llm-openai-api-key.enc.json'),
    path.join(f.userDataDir, 'llm-anthropic-api-key.enc.json')
  );
  assert.throws(
    () => f.restart().readApiKey('anthropic'),
    (error) => error instanceof CredentialStorageError && error.code === 'invalid_data'
  );
  assert.equal(f.restart().readApiKey('openai'), 'key-openai');
});

test('unreadable preferences do not silently select a default provider', (t) => {
  const f = fixture(t);
  fs.writeFileSync(path.join(f.userDataDir, 'ai-connection-preferences.enc.json'), 'broken');
  assert.throws(
    () => f.store.readPreferences(),
    (error) => error instanceof CredentialStorageError && error.code === 'invalid_data'
  );
});

test('unavailable encryption prevents writes without deleting previous settings or keys', (t) => {
  const f = fixture(t);
  f.store.saveApiKey('openai', 'key-openai');
  f.safeStorage.isEncryptionAvailable = () => false;
  for (const operation of [
    () => f.store.savePreferences({ ...EMPTY_CONNECTION_PREFERENCES, model: 'custom' }),
    () => f.store.saveApiKey('openai', 'new-key'),
    () => f.store.saveWebSearchKey('tvly-key'),
  ])
    assert.throws(
      operation,
      (error) => error instanceof CredentialStorageError && error.code === 'encryption_unavailable'
    );
  f.safeStorage.isEncryptionAvailable = () => true;
  assert.equal(f.restart().readApiKey('openai'), 'key-openai');
  assert.equal(f.restart().readWebSearchKey(), null);
});

test('the settings boundary normalizes custom models and rejects unknown providers and methods', () => {
  const draft = { ...EMPTY_CONNECTION_PREFERENCES, model: ' custom-model ' };
  assert.deepEqual(ConnectionPreferencesSchema.parse(draft), { ...draft, model: 'custom-model' });
  for (const provider of ['gemini', 'azure_openai', 'bedrock', 'openrouter'])
    assert.equal(ConnectionPreferencesSchema.safeParse({ ...draft, provider }).success, false);
  assert.equal(ConnectionPreferencesSchema.safeParse({ ...draft, method: 'cloud' }).success, false);
});
