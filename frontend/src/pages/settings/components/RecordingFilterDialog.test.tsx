import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { RecordingFilterDialog } from './RecordingFilterDialog';
import type { CaptureFilter, InstalledApp, Translate } from '../types';

const originalShowModal = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'showModal');
const originalClose = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'close');
const showModal = vi.fn(function (this: HTMLDialogElement) {
  this.setAttribute('open', '');
});
const closeDialog = vi.fn(function (this: HTMLDialogElement) {
  this.removeAttribute('open');
});

// The identity translator keeps assertions on message keys, not on copy.
const translate = ((key: string, vars?: Record<string, string | number>) =>
  vars ? `${key}:${Object.values(vars).join(',')}` : key) as Translate;

const SLACK_ICON = 'data:image/png;base64,slack';
const CHROME_ICON = 'data:image/png;base64,chrome';

const INSTALLED_APPS: InstalledApp[] = [
  { name: 'Slack', bundleId: 'com.tinyspeck.slackmacgap', iconDataUrl: SLACK_ICON },
  { name: 'Google Chrome', bundleId: 'com.google.Chrome', iconDataUrl: CHROME_ICON },
];

const EMPTY_FILTER: CaptureFilter = {
  apps: { mode: 'exclude', entries: [] },
  websites: { mode: 'exclude', hosts: [] },
};

function renderDialog(
  filter: CaptureFilter = EMPTY_FILTER,
  apps: { installedApps?: InstalledApp[]; isLoadingInstalledApps?: boolean } = {}
) {
  const onSubmit = vi.fn();
  const onCancel = vi.fn();
  render(
    <RecordingFilterDialog
      filter={filter}
      installedApps={apps.installedApps ?? INSTALLED_APPS}
      installedAppsError={null}
      isLoadingInstalledApps={apps.isLoadingInstalledApps ?? false}
      isOpen
      saveError={null}
      t={translate}
      onCancel={onCancel}
      onSubmit={onSubmit}
    />
  );
  return { onCancel, onSubmit };
}

function appsMode() {
  return screen.getByLabelText('settings.recordingFilter.apps.modeLabel');
}

function websitesMode() {
  return screen.getByLabelText('settings.recordingFilter.websites.modeLabel');
}

describe('RecordingFilterDialog', () => {
  beforeEach(() => {
    Object.defineProperties(HTMLDialogElement.prototype, {
      showModal: { configurable: true, value: showModal },
      close: { configurable: true, value: closeDialog },
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    if (originalShowModal) {
      Object.defineProperty(HTMLDialogElement.prototype, 'showModal', originalShowModal);
    } else {
      Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal');
    }
    if (originalClose) {
      Object.defineProperty(HTMLDialogElement.prototype, 'close', originalClose);
    } else {
      Reflect.deleteProperty(HTMLDialogElement.prototype, 'close');
    }
  });

  it('opens in exclude mode for both columns', () => {
    renderDialog();
    expect(showModal).toHaveBeenCalledOnce();
    expect(appsMode()).toHaveValue('exclude');
    expect(websitesMode()).toHaveValue('exclude');
  });

  it('adds an app from the picker and submits it with the chosen mode', () => {
    const { onSubmit } = renderDialog();

    fireEvent.change(appsMode(), { target: { value: 'include_only' } });
    fireEvent.click(screen.getByText('settings.recordingFilter.apps.add'));
    fireEvent.change(screen.getByLabelText('settings.recordingFilter.apps.searchPlaceholder'), {
      target: { value: 'chr' },
    });
    expect(screen.queryByText('Slack')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Google Chrome'));
    fireEvent.click(screen.getByText('settings.recordingFilter.submit'));

    expect(onSubmit).toHaveBeenCalledWith({
      apps: {
        mode: 'include_only',
        entries: [{ name: 'Google Chrome', bundleId: 'com.google.Chrome' }],
      },
      websites: { mode: 'exclude', hosts: [] },
    });
  });

  it('adds a website by domain and removes a listed one', () => {
    const { onSubmit } = renderDialog({
      apps: { mode: 'exclude', entries: [] },
      websites: { mode: 'exclude', hosts: ['old.example.com'] },
    });

    fireEvent.click(screen.getByLabelText('settings.recordingFilter.removeEntry:old.example.com'));
    fireEvent.click(screen.getByText('settings.recordingFilter.websites.add'));
    fireEvent.change(screen.getByLabelText('settings.recordingFilter.websites.inputLabel'), {
      target: { value: 'https://Docs.Example.com/team' },
    });
    fireEvent.click(screen.getByText('common.save'));
    fireEvent.click(screen.getByText('settings.recordingFilter.submit'));

    expect(onSubmit).toHaveBeenCalledWith({
      apps: { mode: 'exclude', entries: [] },
      websites: { mode: 'exclude', hosts: ['docs.example.com'] },
    });
  });

  it('reports an unusable domain instead of saving it', () => {
    renderDialog();

    fireEvent.click(screen.getByText('settings.recordingFilter.websites.add'));
    fireEvent.change(screen.getByLabelText('settings.recordingFilter.websites.inputLabel'), {
      target: { value: 'not a host' },
    });
    fireEvent.click(screen.getByText('common.save'));

    expect(screen.getByRole('alert')).toHaveTextContent(
      'settings.recordingFilter.websites.invalidHost'
    );
  });

  it('shows the installed icon for a listed app, including a legacy name-only entry', () => {
    renderDialog({
      // A migrated legacy entry keeps only the display name, so the bundle-id key the
      // picker uses cannot find its icon.
      apps: {
        mode: 'exclude',
        entries: [
          { name: 'Google Chrome', bundleId: 'com.google.Chrome' },
          { name: 'Slack', bundleId: null },
        ],
      },
      websites: { mode: 'exclude', hosts: [] },
    });

    const rows = screen.getByLabelText('settings.recordingFilter.apps.listLabel');
    const icons = rows.querySelectorAll('img.recording-filter-row-icon');
    expect([...icons].map((icon) => icon.getAttribute('src'))).toEqual([CHROME_ICON, SLACK_ICON]);
    expect(
      screen.queryByLabelText('settings.recordingFilter.apps.notInstalled')
    ).not.toBeInTheDocument();
  });

  it('keeps an uninstalled app listed with a placeholder that says it was not found', () => {
    const { onSubmit } = renderDialog({
      apps: {
        mode: 'exclude',
        entries: [{ name: 'Retired App', bundleId: 'com.example.retired' }],
      },
      websites: { mode: 'exclude', hosts: [] },
    });

    const placeholder = screen.getByLabelText('settings.recordingFilter.apps.notInstalled');
    expect(placeholder).toHaveAttribute('title', 'settings.recordingFilter.apps.notInstalled');
    expect(placeholder.tagName).toBe('SPAN');

    // The entry stays editable: it can still be submitted, and still be removed.
    fireEvent.click(screen.getByText('settings.recordingFilter.submit'));
    expect(onSubmit).toHaveBeenCalledWith({
      apps: {
        mode: 'exclude',
        entries: [{ name: 'Retired App', bundleId: 'com.example.retired' }],
      },
      websites: { mode: 'exclude', hosts: [] },
    });
    fireEvent.click(screen.getByLabelText('settings.recordingFilter.removeEntry:Retired App'));
    expect(screen.queryByText('Retired App')).not.toBeInTheDocument();
  });

  it('does not call an app missing while the installed-app list is still loading', () => {
    renderDialog(
      {
        apps: {
          mode: 'exclude',
          entries: [{ name: 'Google Chrome', bundleId: 'com.google.Chrome' }],
        },
        websites: { mode: 'exclude', hosts: [] },
      },
      { installedApps: [], isLoadingInstalledApps: true }
    );

    expect(
      screen.queryByLabelText('settings.recordingFilter.apps.notInstalled')
    ).not.toBeInTheDocument();
  });
});
