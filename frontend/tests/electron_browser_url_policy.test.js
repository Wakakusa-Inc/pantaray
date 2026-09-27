const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { test } = require('node:test');

const { decideBrowserUrl } = require('../electron/dist/privacy/browserUrlPolicy.js');

const CASES_PATH = path.join(__dirname, 'fixtures/zanei_privacy_parity_cases.json');
const CASES = fs.readFileSync(CASES_PATH);
const FIXTURE = JSON.parse(CASES.toString('utf8'));

/** The recorder's own outcome names, so the fixture is read exactly as it is written. */
function outcome(decision) {
  if (decision.kind === 'unavailable') return 'UrlUnavailable';
  if (decision.kind === 'site') return 'Allow';
  return decision.preset === 'authentication' ? 'AuthenticationUrl' : 'PaymentUrl';
}

test('the vendored capture-policy cases are the ones the pinned recorder release ships', () => {
  const release = JSON.parse(
    fs.readFileSync(path.join(__dirname, '../electron/zanei_release.json'), 'utf8')
  );
  // `scripts/stage-zanei-runtime.js` checks the same digest against the release tag,
  // so this pins the vendored copy to bytes that were verified to be the recorder's.
  assert.equal(createHash('sha256').update(CASES).digest('hex'), release.privacyParityCasesSHA256);
});

test('the cases were recorded under the policy this module hard-codes', () => {
  // `zaneiConfig.ts` always writes both blocks, and `capture_screen` has no setting
  // that could turn them off, so the rule is stated here without its flags. If the
  // recorder's own cases stop being recorded that way, the parity below is not parity.
  assert.deepEqual(FIXTURE.policy.browser, {
    mode: 'all_sites',
    default_policy: 'block',
    on_url_unavailable: 'block',
    block_auth: true,
    block_payments: true,
    allow_list: [],
    block_list: [],
  });
});

test('every recorder case decides the same way here', () => {
  for (const [url, expected] of FIXTURE.preset_cases) {
    assert.equal(outcome(decideBrowserUrl(url)), expected, `${url}`);
  }
});

test('a capturable page is named by its host alone, lowercased as the filter stores it', () => {
  assert.deepEqual(decideBrowserUrl('https://Docs.Example.COM/blog/login-guide?q=1#login-form'), {
    kind: 'site',
    host: 'docs.example.com',
  });
});
