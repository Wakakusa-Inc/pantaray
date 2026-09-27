const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { test } = require('node:test');

const { ensureLogSalt, LOG_SALT_FILENAME } = require('../electron/log_salt');

function freshDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'pantaray-salt-'));
}

function withoutEnvSalt(run) {
  const prev = process.env.PANTARAY_LOG_SALT;
  delete process.env.PANTARAY_LOG_SALT;
  try {
    run();
  } finally {
    if (prev === undefined) delete process.env.PANTARAY_LOG_SALT;
    else process.env.PANTARAY_LOG_SALT = prev;
  }
}

test('ensureLogSalt returns the existing env salt and does not persist', () => {
  const prev = process.env.PANTARAY_LOG_SALT;
  process.env.PANTARAY_LOG_SALT = 'env-salt';
  try {
    const dir = freshDir();
    assert.equal(ensureLogSalt(dir), 'env-salt');
    assert.equal(fs.existsSync(path.join(dir, LOG_SALT_FILENAME)), false);
  } finally {
    if (prev === undefined) delete process.env.PANTARAY_LOG_SALT;
    else process.env.PANTARAY_LOG_SALT = prev;
  }
});

test('ensureLogSalt generates, persists, and reuses a salt when env is unset', () => {
  withoutEnvSalt(() => {
    const dir = freshDir();
    const salt = ensureLogSalt(dir);
    assert.ok(salt.length >= 32);

    const saltFile = path.join(dir, LOG_SALT_FILENAME);
    assert.equal(fs.existsSync(saltFile), true);
    assert.equal(fs.readFileSync(saltFile, 'utf8').trim(), salt);

    // 2 回目は永続化済みの salt を再利用する（起動間で安定）。
    assert.equal(ensureLogSalt(dir), salt);
  });
});
