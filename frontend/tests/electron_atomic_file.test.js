const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { writeFileAtomic } = require('../electron/dist/atomicFile');

function setup(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'atomic-image-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return { target: path.join(root, 'images/image.png'), temp: path.join(root, '.tmp') };
}

test('image writes replace complete content with owner-only permissions and no temporary files', (t) => {
  const { target, temp } = setup(t);
  fs.mkdirSync(path.dirname(target));
  fs.writeFileSync(target, 'old image', { mode: 0o644 });
  writeFileAtomic(target, temp, Buffer.from('new image'));
  assert.equal(fs.readFileSync(target, 'utf8'), 'new image');
  assert.equal(fs.statSync(target).mode & 0o777, 0o600);
  assert.deepEqual(fs.readdirSync(temp), []);
});

for (const operation of ['writeFileSync', 'renameSync']) {
  test(`a failed ${operation} preserves the previous image and removes the incomplete file`, (t) => {
    const { target, temp } = setup(t);
    fs.mkdirSync(path.dirname(target));
    fs.writeFileSync(target, 'previous image');
    const failure = Object.assign(new Error('filesystem refused write'), { code: 'EACCES' });
    t.mock.method(fs, operation, () => {
      throw failure;
    });
    assert.throws(() => writeFileAtomic(target, temp, Buffer.from('replacement')), failure);
    assert.equal(fs.readFileSync(target, 'utf8'), 'previous image');
    assert.deepEqual(fs.readdirSync(temp), []);
  });
}
