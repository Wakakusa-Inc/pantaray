const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { test } = require('node:test');

const { build } = require('../package.json');

test('electron-builder config avoids maximum compression for bundled local backend runtime', () => {
  assert.equal(build.compression, 'normal');
});

test('electron-builder config includes macOS tray status icons', () => {
  assert.ok(build.files.includes('assets/icons/Pantaray_tray_*.png'));
});

test('macOS build declares the screen recording purpose string and entitlement', () => {
  // Without both, macOS refuses the capture and `capture_screen` can only report
  // a missing permission the user has no way to grant.
  assert.equal(
    build.mac.extendInfo.NSScreenCaptureUsageDescription,
    'Pantaray captures your screen only when you ask an Action to look at it.'
  );
  const entitlements = fs.readFileSync(path.join(__dirname, '..', build.mac.entitlements), 'utf8');
  assert.ok(entitlements.includes('<key>com.apple.security.device.screen-capture</key>'));
});
