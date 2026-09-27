const assert = require('assert');
const { test } = require('node:test');

const { buildSigningEnvValidation } = require('../scripts/require-macos-signing-env.js');
const notarize = require('../scripts/notarize.js');

async function withEnv(overrides, fn) {
  const originalEnv = { ...process.env };

  try {
    for (const key of Object.keys(process.env)) {
      delete process.env[key];
    }
    Object.assign(process.env, overrides);
    return await fn();
  } finally {
    for (const key of Object.keys(process.env)) {
      delete process.env[key];
    }
    Object.assign(process.env, originalEnv);
  }
}

test('require-macos-signing-env: release mode fails when Apple notarization env is missing', () => {
  const result = buildSigningEnvValidation({
    platform: 'darwin',
    env: {
      PANTARAY_RELEASE_BUILD: '1',
      CSC_NAME: '0123456789ABCDEF0123456789ABCDEF01234567',
    },
  });

  assert.equal(result.ok, false);
  assert.match(result.message, /APPLE_ID/);
  assert.match(result.message, /APPLE_APP_SPECIFIC_PASSWORD/);
  assert.match(result.message, /APPLE_TEAM_ID/);
});

test('require-macos-signing-env: release mode fails when signing env is missing', () => {
  const result = buildSigningEnvValidation({
    platform: 'darwin',
    env: {
      PANTARAY_RELEASE_BUILD: '1',
      APPLE_ID: 'developer@example.test',
      APPLE_APP_SPECIFIC_PASSWORD: 'app-password',
      APPLE_TEAM_ID: 'TEAMID1234',
    },
  });

  assert.deepEqual(result, {
    ok: false,
    message: 'CSC_NAME or CSC_LINK is required for signed macOS build.',
  });
});

test('require-macos-signing-env: local signed mode does not require Apple notarization env', () => {
  const result = buildSigningEnvValidation({
    platform: 'darwin',
    env: {
      CSC_NAME: '0123456789ABCDEF0123456789ABCDEF01234567',
    },
  });

  assert.deepEqual(result, { ok: true });
});

test('require-macos-signing-env: non-macOS is a no-op even in release mode', () => {
  const result = buildSigningEnvValidation({
    platform: 'linux',
    env: {
      PANTARAY_RELEASE_BUILD: '1',
    },
  });

  assert.deepEqual(result, { ok: true });
});

test('notarize: local mode skips when Apple credentials are missing', async () => {
  await withEnv({}, async () => {
    await notarize.default({
      electronPlatformName: 'darwin',
      packager: { appInfo: { productFilename: 'Pantaray' } },
      appOutDir: '/missing',
    });
  });
});

test('notarize: release mode fails when Apple credentials are missing', async () => {
  await withEnv({ PANTARAY_RELEASE_BUILD: '1' }, async () => {
    await assert.rejects(
      () =>
        notarize.default({
          electronPlatformName: 'darwin',
          packager: { appInfo: { productFilename: 'Pantaray' } },
          appOutDir: '/missing',
        }),
      /Notarization credentials are required for release macOS build/
    );
  });
});

test('notarize: non-macOS release mode skips before checking Apple credentials', async () => {
  await withEnv({ PANTARAY_RELEASE_BUILD: '1' }, async () => {
    await notarize.default({
      electronPlatformName: 'linux',
      packager: { appInfo: { productFilename: 'Pantaray' } },
      appOutDir: '/missing',
    });
  });
});

test('notarizeWithRetry retries transient upload timeouts', async () => {
  let attempts = 0;
  const delays = [];

  await notarize.notarizeWithRetry(
    async () => {
      attempts += 1;
      if (attempts < 3) {
        throw new Error('abortedUpload error: HTTPClientError.connectTimeout');
      }
    },
    { appPath: '/tmp/Pantaray.app' },
    { log() {}, warn() {} },
    async (delayMs) => {
      delays.push(delayMs);
    }
  );

  assert.equal(attempts, 3);
  assert.deepEqual(delays, [15_000, 30_000]);
});

test('notarizeWithRetry does not retry non-transient notarization failures', async () => {
  let attempts = 0;

  await assert.rejects(
    () =>
      notarize.notarizeWithRetry(
        async () => {
          attempts += 1;
          throw new Error('Invalid credentials');
        },
        { appPath: '/tmp/Pantaray.app' },
        { log() {}, warn() {} },
        async () => {}
      ),
    /Invalid credentials/
  );

  assert.equal(attempts, 1);
});
