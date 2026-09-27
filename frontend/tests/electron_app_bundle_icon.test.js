const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test } = require('node:test');

const { readAppBundleIconPng, selectIcnsPng } = require('../electron/dist/privacy/appBundleIcon');

const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

/** Enough of a PNG for the parser's contract: signature, IHDR width, IHDR height. */
function pngHeader(width) {
  const png = Buffer.alloc(24);
  PNG_SIGNATURE.copy(png, 0);
  png.writeUInt32BE(13, 8);
  png.write('IHDR', 12, 'ascii');
  png.writeUInt32BE(width, 16);
  png.writeUInt32BE(width, 20);
  return png;
}

function icnsElement(type, payload) {
  const element = Buffer.alloc(8 + payload.length);
  element.write(type, 0, 'ascii');
  element.writeUInt32BE(element.length, 4);
  payload.copy(element, 8);
  return element;
}

function icns(elements) {
  const body = Buffer.concat(elements);
  const file = Buffer.alloc(8 + body.length);
  file.write('icns', 0, 'ascii');
  file.writeUInt32BE(file.length, 4);
  body.copy(file, 8);
  return file;
}

test('selectIcnsPng: takes the smallest variant at or above the render size', () => {
  const file = icns([
    // A legacy ARGB variant: sized like a PNG element but not one, so trusting the
    // element type instead of the payload would hand raw pixels to the decoder.
    icnsElement('ic09', Buffer.from('ARGBnot-a-png-payload-at-all')),
    icnsElement('ic11', pngHeader(32)),
    icnsElement('ic10', pngHeader(1024)),
    icnsElement('ic07', pngHeader(128)),
  ]);

  // 128 over 1024: an 18 px row must not cost a megapixel decode per application.
  assert.deepEqual(selectIcnsPng(file), pngHeader(128));
});

test('selectIcnsPng: falls back to the largest variant when every one is small', () => {
  const file = icns([icnsElement('icp4', pngHeader(16)), icnsElement('icp5', pngHeader(32))]);

  assert.deepEqual(selectIcnsPng(file), pngHeader(32));
});

test('selectIcnsPng: stops on a malformed element table instead of looping', () => {
  const file = icns([icnsElement('ic07', pngHeader(128))]);
  // A length that does not advance past its own header would otherwise spin forever.
  file.writeUInt32BE(0, 12);

  assert.equal(selectIcnsPng(file), null);
  assert.equal(selectIcnsPng(Buffer.from('not an icns file at all')), null);
});

test('readAppBundleIconPng: a bundle that names no icon file reads as no icon', (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'icon-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const bundlePath = path.join(root, 'Fixture.app');
  fs.mkdirSync(path.join(bundlePath, 'Contents'), { recursive: true });
  fs.writeFileSync(
    path.join(bundlePath, 'Contents/Info.plist'),
    '<?xml version="1.0" encoding="UTF-8"?>\n' +
      '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n' +
      '<plist version="1.0"><dict><key>CFBundleIdentifier</key><string>com.example.fixture</string></dict></plist>\n'
  );

  // Apps that draw their icon from an asset catalog reach this path, and the picker
  // enumerates every installed bundle in one pass: a throw would lose the whole list.
  assert.equal(readAppBundleIconPng(bundlePath), null);
});

test('readAppBundleIconPng: real bundles yield their own distinct artwork', (t) => {
  const bundles = ['/Applications/Google Chrome.app', '/System/Applications/Calculator.app'];
  if (!bundles.every((bundlePath) => fs.existsSync(bundlePath))) {
    t.skip('needs Google Chrome and Calculator installed');
    return;
  }

  const icons = bundles.map((bundlePath) => readAppBundleIconPng(bundlePath));
  for (const icon of icons) {
    assert.ok(icon, 'every installed bundle carries a readable icon');
    assert.deepEqual(icon.subarray(0, 8), PNG_SIGNATURE);
    assert.ok(icon.readUInt32BE(16) >= 128);
  }
  // The defect this reader replaces: `app.getFileIcon` answered with one
  // byte-identical placeholder for every application, so the picker showed the same
  // grey square for Chrome, Slack and Pantaray alike.
  assert.notDeepEqual(icons[0], icons[1]);
});
