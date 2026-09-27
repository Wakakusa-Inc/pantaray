import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

import { RecordingFilterSection } from './RecordingFilterSection';
import type { CaptureAppEntry, CaptureFilter, InstalledApp, Translate } from '../types';

// The identity translator keeps assertions on message keys, not on copy.
const translate = ((key: string, vars?: Record<string, string | number>) =>
  vars ? `${key}:${Object.values(vars).join(',')}` : key) as Translate;

const CHROME_ICON = 'data:image/png;base64,chrome';

function entry(name: string): CaptureAppEntry {
  return { name, bundleId: `com.example.${name.toLowerCase()}` };
}

function renderSection(filter: Partial<CaptureFilter>, installedApps: InstalledApp[] = []) {
  render(
    <RecordingFilterSection
      hasCaptureSettings={true}
      captureFilter={{
        apps: { mode: 'exclude', entries: [] },
        websites: { mode: 'exclude', hosts: [] },
        ...filter,
      }}
      captureFilterError={null}
      installedApps={installedApps}
      isLoadingCaptureFilter={false}
      openFilterDialog={vi.fn()}
      t={translate}
    />
  );
}

afterEach(cleanup);

it('draws each listed app with the icon from the enumeration', () => {
  renderSection({ apps: { mode: 'exclude', entries: [entry('Chrome'), entry('Slack')] } }, [
    { name: 'Chrome', bundleId: 'com.example.chrome', iconDataUrl: CHROME_ICON },
    { name: 'Slack', bundleId: 'com.example.slack', iconDataUrl: null },
  ]);

  const chips = within(
    screen.getByRole('list', { name: 'settings.recordingFilter.apps.listLabel' })
  ).getAllByRole('listitem');
  expect(chips.map((chip) => chip.textContent)).toEqual(['Chrome', 'Slack']);
  // An app whose icon could not be read still reads as a row, not as a broken image.
  expect(chips[0].querySelector('img')?.getAttribute('src')).toBe(CHROME_ICON);
  expect(chips[1].querySelector('img')).toBeNull();
});

it('collapses everything past the chip limit into one count', () => {
  const entries = Array.from({ length: 11 }, (_, index) => entry(`App${index}`));
  renderSection({ apps: { mode: 'exclude', entries } });

  const chips = within(
    screen.getByRole('list', { name: 'settings.recordingFilter.apps.listLabel' })
  ).getAllByRole('listitem');
  // Eight named apps plus the remainder: the summary must stay one glance wide.
  expect(chips).toHaveLength(9);
  expect(chips[8]).toHaveTextContent('settings.recordingFilter.summary.more:3');
});

it('lists websites as their own chips and says so when there are none', () => {
  renderSection({ websites: { mode: 'exclude', hosts: ['example.com', 'mail.example.jp'] } });

  const chips = within(
    screen.getByRole('list', { name: 'settings.recordingFilter.websites.listLabel' })
  ).getAllByRole('listitem');
  expect(chips.map((chip) => chip.textContent)).toEqual(['example.com', 'mail.example.jp']);
  expect(screen.getByText('settings.recordingFilter.summary.none')).toBeTruthy();
  expect(
    screen.queryByRole('list', { name: 'settings.recordingFilter.apps.listLabel' })
  ).toBeNull();
});

it.each([true, false])('hides the unverified filter summary while loading=%s', (loading) => {
  render(
    <RecordingFilterSection
      hasCaptureSettings={false}
      captureFilter={{
        apps: { mode: 'exclude', entries: [] },
        websites: { mode: 'exclude', hosts: [] },
      }}
      captureFilterError={loading ? null : 'read failed'}
      installedApps={[]}
      isLoadingCaptureFilter={loading}
      openFilterDialog={vi.fn()}
      t={translate}
    />
  );
  expect(screen.getByRole('button')).toBeDisabled();
  expect(screen.queryByText('settings.recordingFilter.summary.none')).toBeNull();
  expect(screen.queryByText('settings.recordingFilter.apps.mode.exclude')).toBeNull();
  if (loading) expect(screen.getByText('settings.loadingStatus')).toBeInTheDocument();
  else expect(screen.getByRole('alert')).toHaveTextContent('read failed');
});
