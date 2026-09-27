const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { test } = require('node:test');

const {
  createActionImageProtocolHandler,
  readVerifiedStoredImage,
} = require('../electron/dist/protocol/imageProtocol.js');
const {
  buildActionImageUrl,
  isValidImageStoragePath,
  sniffImageMimeType,
} = require('../electron/dist/protocol/imageStoragePath.js');

const UUID = '550e8400-e29b-41d4-a716-446655440000';
const PNG = Buffer.concat([
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
  Buffer.from('pixels'),
]);
const JPEG = Buffer.concat([Buffer.from([0xff, 0xd8, 0xff, 0xe0]), Buffer.from('pixels')]);

function createRoot() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pantaray-image-'));
  return {
    root,
    write: (storagePath, bytes) => {
      const target = path.join(root, 'generated', 'images', storagePath);
      fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.writeFileSync(target, bytes);
      return target;
    },
  };
}

function createHandler(root, userId = 'user-1') {
  return createActionImageProtocolHandler({
    localArtifactRoot: root,
    getCurrentSubjectId: () => userId,
  });
}

// Mirrors agents/tests/unit/security/test_storage_paths.py so the TypeScript port cannot drift
// from the Python reader that ultimately opens the same file.
test('image storage paths follow the same rules as the Python validator', () => {
  const cases = [
    ['user-1', `user-1/2025-12-28/${UUID}.png`, true],
    ['user-1', `user-1/2025-12-28/${UUID}.gif`, true],
    ['user-1', `user-1/2025-12-28/${UUID}.jpeg`, true],
    ['user-1', `user-1/2025-12-28/${UUID}.jpg`, true],
    ['user-1', `user-1/2025-12-28/${UUID}.webp`, true],
    // prefix mismatch
    ['user-1', `user-2/2025-12-28/${UUID}.png`, false],
    // invalid date
    ['user-1', `user-1/2025-99-99/${UUID}.png`, false],
    ['user-1', `user-1/20251228/${UUID}.png`, false],
    // invalid uuid
    ['user-1', 'user-1/2025-12-28/not-a-uuid.png', false],
    // disallowed extension
    ['user-1', `user-1/2025-12-28/${UUID}.pdf`, false],
    ['user-1', `user-1/2025-12-28/${UUID}.svg`, false],
    ['user-1', `user-1/2025-12-28/${UUID}.bmp`, false],
    // extra path segments
    ['user-1', `user-1/2025-12-28/sub/${UUID}.png`, false],
    // traversal-like
    ['user-1', 'user-1/2025-12-28/../x.png', false],
    ['user-1', `user-1\\2025-12-28\\${UUID}.png`, false],
    // control chars
    ['user-1', `user-1/2025-12-28/\n${UUID}.png`, false],
    // empty
    ['user-1', '', false],
    ['', `user-1/2025-12-28/${UUID}.png`, false],
  ];
  for (const [userId, storagePath, expected] of cases) {
    assert.equal(
      isValidImageStoragePath({ userId, storagePath }),
      expected,
      `${JSON.stringify(storagePath)} for ${JSON.stringify(userId)}`
    );
  }
  assert.equal(
    isValidImageStoragePath({ userId: 'user-1', storagePath: `user-1/2025-12-28/${UUID}.png` }),
    true
  );
  assert.equal(
    isValidImageStoragePath({
      userId: 'user-1',
      storagePath: `user-1/2025-12-28/${UUID}.png`,
      maxLength: 20,
    }),
    false
  );
});

test('magic bytes decide the media type, not the declared extension', () => {
  assert.equal(sniffImageMimeType(PNG), 'image/png');
  assert.equal(sniffImageMimeType(JPEG), 'image/jpeg');
  assert.equal(sniffImageMimeType(Buffer.from('GIF89a....')), 'image/gif');
  assert.equal(sniffImageMimeType(Buffer.from('RIFF????WEBPVP8 ')), 'image/webp');
  assert.equal(sniffImageMimeType(Buffer.from('<svg xmlns=')), null);
  assert.equal(sniffImageMimeType(Buffer.alloc(0)), null);
});

test('the image protocol serves a stored image with fail-closed response headers', async () => {
  const store = createRoot();
  const storagePath = `user-1/2026-09-08/${UUID}.png`;
  store.write(storagePath, PNG);

  const response = await createHandler(store.root)({ url: buildActionImageUrl(storagePath) });

  assert.equal(response.status, 200);
  assert.equal(response.headers.get('Content-Type'), 'image/png');
  assert.equal(response.headers.get('Content-Length'), String(PNG.byteLength));
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
  assert.equal(response.headers.get('X-Content-Type-Options'), 'nosniff');
  assert.equal(response.headers.get('Content-Disposition'), 'inline');
  assert.equal(response.headers.get('Content-Security-Policy'), "default-src 'none'; sandbox");
  assert.deepEqual(Buffer.from(await response.arrayBuffer()), PNG);
});

test('the image protocol refuses another user, a foreign host, and traversal', async () => {
  const store = createRoot();
  const own = `user-1/2026-09-08/${UUID}.png`;
  const other = `user-2/2026-09-08/${UUID}.png`;
  store.write(own, PNG);
  store.write(other, PNG);
  const handler = createHandler(store.root);

  for (const url of [
    buildActionImageUrl(other),
    `pantaray-image://elsewhere/${own}`,
    'https://local/user-1/2026-09-08/x.png',
    `pantaray-image://local/user-1/2026-09-08/..%2f..%2f..%2fetc%2fpasswd`,
    `pantaray-image://local/user-1/2026-09-08%2fsub%2f${UUID}.png`,
    buildActionImageUrl(`user-1/2026-09-08/${UUID}.png.txt`),
  ]) {
    assert.equal((await handler({ url })).status, 404, url);
  }
  assert.equal((await handler({ url: buildActionImageUrl(own) })).status, 200);
});

test('the image protocol refuses a symlink that escapes the image directory', async () => {
  const store = createRoot();
  const secret = path.join(store.root, 'secret.png');
  fs.writeFileSync(secret, PNG);
  const linkPath = path.join(store.root, 'generated', 'images', 'user-1', '2026-09-08');
  fs.mkdirSync(linkPath, { recursive: true });
  const storagePath = `user-1/2026-09-08/${UUID}.png`;
  fs.symlinkSync(secret, path.join(linkPath, `${UUID}.png`));

  const response = await createHandler(store.root)({ url: buildActionImageUrl(storagePath) });

  assert.equal(response.status, 404);
});

test('the image protocol refuses content that disagrees with its extension', async () => {
  const store = createRoot();
  const storagePath = `user-1/2026-09-08/${UUID}.png`;
  store.write(storagePath, JPEG);

  assert.equal(
    (await createHandler(store.root)({ url: buildActionImageUrl(storagePath) })).status,
    404
  );
});

test('the image protocol refuses everything while no user is signed in', async () => {
  const store = createRoot();
  const storagePath = `user-1/2026-09-08/${UUID}.png`;
  store.write(storagePath, PNG);

  const handler = createActionImageProtocolHandler({
    localArtifactRoot: store.root,
    getCurrentSubjectId: () => null,
  });

  assert.equal((await handler({ url: buildActionImageUrl(storagePath) })).status, 404);
});

test('reading a stored image resolves the absolute path only after every check passes', () => {
  const store = createRoot();
  const storagePath = `user-1/2026-09-08/${UUID}.png`;
  const absolutePath = store.write(storagePath, PNG);
  const deps = { localArtifactRoot: store.root, getCurrentSubjectId: () => 'user-1' };

  const image = readVerifiedStoredImage(deps, storagePath);

  assert.equal(image.absolutePath, fs.realpathSync(absolutePath));
  assert.equal(image.mimeType, 'image/png');
  assert.equal(readVerifiedStoredImage(deps, `user-1/2026-09-08/${UUID}.webp`), null);
  assert.equal(readVerifiedStoredImage(deps, `user-2/2026-09-08/${UUID}.png`), null);
});
