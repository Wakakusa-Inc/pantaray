const assert = require('assert');
const { createHash } = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { test } = require('node:test');

const { answerScreenCapture } = require('../electron/dist/capture/screenCapture.js');
const { isAlwaysDeniedCaptureApp } = require('../electron/dist/privacy/alwaysDeniedCaptureApps.js');
const { isValidImageStoragePath } = require('../electron/dist/protocol/imageStoragePath.js');

const PNG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x70, 0x69, 0x78]);

function settings(overrides = {}) {
  return {
    version: 2,
    apps: { mode: 'exclude', entries: [] },
    websites: { mode: 'exclude', hosts: [] },
    ideFileRules: { mode: 'on', onFileNameUnavailable: 'allow', sensitivePresets: {} },
    ...overrides,
  };
}

function harness(overrides = {}) {
  const localArtifactRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'pantaray-capture-'));
  const captures = [];
  const written = [];
  const deps = {
    readScreenRecordingStatus: () => 'granted',
    getCaptureSettings: () => settings(),
    isCaptureEditing: () => false,
    readFrontmostApplication: async () => ({ name: 'Finder', bundleId: 'com.apple.finder' }),
    readBrowserUrl: async () => null,
    capturePrimaryDisplay: async () => {
      captures.push('captured');
      return { png: PNG, widthPx: 1440, heightPx: 900 };
    },
    getCurrentSubjectId: () => 'user-1',
    localArtifactRoot: () => localArtifactRoot,
    writeFileAtomic: (targetPath, _tempDirectoryPath, payload) => {
      fs.mkdirSync(path.dirname(targetPath), { recursive: true });
      fs.writeFileSync(targetPath, payload);
      written.push(targetPath);
    },
    now: () => new Date('2026-09-08T00:00:00.000Z'),
    ...overrides,
  };
  return { deps, captures, written, localArtifactRoot };
}

test('a granted capture is written under the user image namespace and described exactly', async () => {
  const { deps, written } = harness();

  const answer = await answerScreenCapture(deps);

  assert.equal(answer.status, 'captured');
  assert.ok(isValidImageStoragePath({ userId: 'user-1', storagePath: answer.storage_path }));
  assert.ok(answer.storage_path.startsWith('user-1/2026-09-08/'));
  assert.equal(answer.mime_type, 'image/png');
  assert.equal(answer.byte_size, PNG.byteLength);
  assert.equal(answer.sha256, createHash('sha256').update(PNG).digest('hex'));
  assert.equal(answer.app_name, 'Finder');
  assert.equal(answer.captured_at, '2026-09-08T00:00:00.000Z');
  assert.equal(written.length, 1);
  assert.deepEqual(fs.readFileSync(written[0]), PNG);
});

test('a missing Screen Recording permission refuses before anything is captured', async () => {
  const { deps, captures } = harness({ readScreenRecordingStatus: () => 'denied' });

  const answer = await answerScreenCapture(deps);

  assert.deepEqual(answer, { status: 'refused', code: 'SCREEN_RECORDING_PERMISSION_REQUIRED' });
  assert.deepEqual(captures, []);
});

test('an unidentifiable frontmost app refuses rather than capturing unfiltered', async () => {
  const { deps, captures } = harness({ readFrontmostApplication: async () => null });

  const answer = await answerScreenCapture(deps);

  assert.equal(answer.code, 'CAPTURE_REFUSED_BY_PRIVACY_FILTER');
  assert.equal(answer.axis, 'app');
  assert.deepEqual(captures, []);
});

test('a password manager is refused even when the filter names it as allowed', async () => {
  const { deps, captures } = harness({
    readFrontmostApplication: async () => ({
      name: '1Password',
      bundleId: 'com.1password.1password',
    }),
    getCaptureSettings: () =>
      settings({
        apps: {
          mode: 'include_only',
          entries: [{ name: '1Password', bundleId: 'com.1password.1password' }],
        },
      }),
  });

  const answer = await answerScreenCapture(deps);

  assert.equal(answer.code, 'CAPTURE_REFUSED_PASSWORD_MANAGER');
  assert.equal(answer.app_name, '1Password');
  assert.deepEqual(captures, []);
});

test('editing the filter refuses until the rules are settled', async () => {
  const { deps, captures } = harness({ isCaptureEditing: () => true });

  const answer = await answerScreenCapture(deps);

  assert.equal(answer.axis, 'editing');
  assert.deepEqual(captures, []);
});

test('an excluded app refuses and an "only these" list refuses everything else', async () => {
  const excluded = harness({
    getCaptureSettings: () =>
      settings({
        apps: { mode: 'exclude', entries: [{ name: 'Finder', bundleId: 'com.apple.finder' }] },
      }),
  });
  const notIncluded = harness({
    getCaptureSettings: () =>
      settings({
        apps: { mode: 'include_only', entries: [{ name: 'Notes', bundleId: 'com.apple.Notes' }] },
      }),
  });

  for (const { deps, captures } of [excluded, notIncluded]) {
    const answer = await answerScreenCapture(deps);
    assert.equal(answer.code, 'CAPTURE_REFUSED_BY_PRIVACY_FILTER');
    assert.equal(answer.axis, 'app');
    assert.equal(answer.app_name, 'Finder');
    assert.deepEqual(captures, []);
  }
});

test('a frontmost app with no readable bundle id refuses instead of passing an exclude list', async () => {
  const { deps, captures } = harness({
    getCaptureSettings: () =>
      settings({
        apps: {
          mode: 'exclude',
          entries: [{ name: 'Slack', bundleId: 'com.tinyspeck.slackmacgap' }],
        },
      }),
    readFrontmostApplication: async () => ({ name: 'Slack', bundleId: null }),
  });

  const answer = await answerScreenCapture(deps);

  assert.equal(answer.code, 'CAPTURE_REFUSED_BY_PRIVACY_FILTER');
  assert.equal(answer.axis, 'app');
  assert.equal(answer.app_name, 'Slack');
  assert.deepEqual(captures, []);
});

test('a browser that reports no URL refuses instead of capturing an unfiltered page', async () => {
  const { deps, captures } = harness({
    readFrontmostApplication: async () => ({
      name: 'Google Chrome',
      bundleId: 'com.google.Chrome',
    }),
    readBrowserUrl: async () => null,
  });

  const answer = await answerScreenCapture(deps);

  assert.equal(answer.code, 'CAPTURE_REFUSED_URL_UNAVAILABLE');
  assert.equal(answer.app_name, 'Google Chrome');
  assert.deepEqual(captures, []);
});

test('an excluded host refuses and names the host but never the window title', async () => {
  const { deps, captures } = harness({
    readFrontmostApplication: async () => ({ name: 'Safari', bundleId: 'com.apple.Safari' }),
    readBrowserUrl: async () => 'https://Mail.Example.com/inbox/secret-thread',
    getCaptureSettings: () =>
      settings({ websites: { mode: 'exclude', hosts: ['mail.example.com'] } }),
  });

  const answer = await answerScreenCapture(deps);

  assert.equal(answer.code, 'CAPTURE_REFUSED_BY_PRIVACY_FILTER');
  assert.equal(answer.axis, 'website');
  assert.equal(answer.host, 'mail.example.com');
  assert.equal(JSON.stringify(answer).includes('secret-thread'), false);
  assert.deepEqual(captures, []);
});

test('a sign-in or payment page on an allowed host refuses without naming it', async () => {
  for (const url of [
    'https://docs.example.com/login',
    'https://docs.example.com/settings/billing',
    'https://docs.example.com/app#/password/reset',
    'https://checkout.example.com/c/abc',
  ]) {
    const { deps, captures } = harness({
      readFrontmostApplication: async () => ({ name: 'Safari', bundleId: 'com.apple.Safari' }),
      readBrowserUrl: async () => url,
      getCaptureSettings: () => settings({ websites: { mode: 'exclude', hosts: [] } }),
    });

    const answer = await answerScreenCapture(deps);

    assert.equal(answer.code, 'CAPTURE_REFUSED_SENSITIVE_PAGE', url);
    assert.equal(answer.app_name, 'Safari');
    // The route is what gave the page away; repeating it leaks what was protected.
    assert.deepEqual(Object.keys(answer).sort(), ['app_name', 'code', 'status']);
    assert.deepEqual(captures, []);
  }
});

test('a page that only reads like a sign-in route is still captured', async () => {
  for (const url of [
    'https://docs.example.com/blog/login-guide',
    'https://docs.example.com/oauth-client-library',
    'https://docs.example.com/payment-method-guide',
    'https://docs.example.com/checkout-history',
    'https://docs.example.com/docs#section-login',
    'https://docs.example.com/docs#login-form',
  ]) {
    const { deps, captures } = harness({
      readFrontmostApplication: async () => ({ name: 'Safari', bundleId: 'com.apple.Safari' }),
      readBrowserUrl: async () => url,
      getCaptureSettings: () =>
        settings({ websites: { mode: 'include_only', hosts: ['docs.example.com'] } }),
    });

    const answer = await answerScreenCapture(deps);

    assert.equal(answer.status, 'captured', url);
    assert.deepEqual(captures, ['captured']);
  }
});

test('a browser page that is not a website at all is refused, not filtered by its host', async () => {
  const { deps, captures } = harness({
    readFrontmostApplication: async () => ({
      name: 'Google Chrome',
      bundleId: 'com.google.Chrome',
    }),
    readBrowserUrl: async () => 'chrome://password-manager/passwords',
  });

  const answer = await answerScreenCapture(deps);

  assert.equal(answer.code, 'CAPTURE_REFUSED_URL_UNAVAILABLE');
  assert.deepEqual(captures, []);
});

test('an allowed browser host is captured', async () => {
  const { deps, captures } = harness({
    readFrontmostApplication: async () => ({ name: 'Safari', bundleId: 'com.apple.Safari' }),
    readBrowserUrl: async () => 'https://docs.example.com/page',
    getCaptureSettings: () =>
      settings({ websites: { mode: 'include_only', hosts: ['docs.example.com'] } }),
  });

  const answer = await answerScreenCapture(deps);

  assert.equal(answer.status, 'captured');
  assert.deepEqual(captures, ['captured']);
});

test('a display that produces no frame is answered, not left to time out', async () => {
  const { deps, written } = harness({ capturePrimaryDisplay: async () => null });

  const answer = await answerScreenCapture(deps);

  assert.equal(answer.code, 'SCREEN_RECORDING_PERMISSION_REQUIRED');
  assert.deepEqual(written, []);
});

test('the always-denied list matches by bundle id and by name, not by prefix', () => {
  assert.equal(
    isAlwaysDeniedCaptureApp({ name: 'Whatever', bundleId: 'com.bitwarden.desktop' }),
    true
  );
  assert.equal(isAlwaysDeniedCaptureApp({ name: 'KeePassXC', bundleId: null }), true);
  assert.equal(
    isAlwaysDeniedCaptureApp({ name: 'Notes', bundleId: 'com.apple.keychainaccess.helper' }),
    false
  );
  assert.equal(isAlwaysDeniedCaptureApp({ name: 'Notes', bundleId: 'com.apple.Notes' }), false);
});
