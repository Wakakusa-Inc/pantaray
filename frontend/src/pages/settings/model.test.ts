import { describe, expect, it } from 'vitest';

import {
  captureAppKey,
  filterInstalledApps,
  normalizeCaptureFilterForUi,
  parseWebsiteHost,
} from './model';

describe('captureAppKey', () => {
  it('identifies an app by bundle id when it has one, matching the recorder', () => {
    expect(captureAppKey({ name: 'Google Chrome', bundleId: 'com.google.Chrome' })).toBe(
      'com.google.chrome'
    );
    expect(captureAppKey({ name: 'Legacy App', bundleId: null })).toBe('legacy app');
  });
});

describe('parseWebsiteHost', () => {
  it.each([
    ['example.com', 'example.com'],
    ['https://Docs.Example.com/team?q=1', 'docs.example.com'],
    ['example.com:8443', 'example.com'],
    ['例え.テスト', 'xn--r8jz45g.xn--zckzah'],
  ])('canonicalizes %s', (input, expected) => {
    expect(parseWebsiteHost(input)).toEqual({ ok: true, host: expected });
  });

  it.each([
    '',
    '   ',
    'localhost',
    'not a host',
    // `URL.hostname` preserves these, but none is a DNS name the recorder can match.
    '*.example.com',
    'foo..bar',
    'exa_mple.com',
    '-example.com',
    'example-.com',
    '.example.com',
    'example.com.',
  ])('rejects %s', (input) => {
    expect(parseWebsiteHost(input)).toEqual({ ok: false, error: 'invalid_host' });
  });
});

describe('normalizeCaptureFilterForUi', () => {
  it('defaults to exclude mode with empty lists', () => {
    expect(normalizeCaptureFilterForUi(null)).toEqual({
      apps: { mode: 'exclude', entries: [] },
      websites: { mode: 'exclude', hosts: [] },
    });
  });

  it('drops entries that would match the same app or host twice', () => {
    const filter = normalizeCaptureFilterForUi({
      apps: {
        mode: 'include_only',
        entries: [
          { name: 'Slack', bundleId: 'com.tinyspeck.slackmacgap' },
          { name: 'Slack (old)', bundleId: 'COM.TINYSPECK.SLACKMACGAP' },
          { name: '  ', bundleId: '  ' },
        ],
      },
      websites: { mode: 'include_only', hosts: ['Example.com', 'example.com', ''] },
    });

    expect(filter.apps.entries).toEqual([{ name: 'Slack', bundleId: 'com.tinyspeck.slackmacgap' }]);
    expect(filter.websites).toEqual({ mode: 'include_only', hosts: ['example.com'] });
  });
});

describe('filterInstalledApps', () => {
  const installed = [
    { name: 'Slack', bundleId: 'com.tinyspeck.slackmacgap', iconDataUrl: null },
    { name: 'Safari', bundleId: 'com.apple.Safari', iconDataUrl: null },
  ];

  it('hides apps already listed and matches on name or bundle id', () => {
    expect(
      filterInstalledApps(installed, 'saf', [
        { name: 'Slack', bundleId: 'com.tinyspeck.slackmacgap' },
      ])
    ).toEqual([installed[1]]);
    expect(filterInstalledApps(installed, 'tinyspeck', [])).toEqual([installed[0]]);
    expect(filterInstalledApps(installed, '', [])).toEqual(installed);
  });
});
