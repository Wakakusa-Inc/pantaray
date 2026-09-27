import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { UpdateReadyNotice as Notice } from '../../electron/src/ipc/context';
import { UiLanguageProvider } from '@/context/UiLanguageContext';
import { UpdateReadyNotice } from './UpdateReadyNotice';

function bridge(initial: Notice | null) {
  const changes = new Set<() => void>();
  const api = {
    getReadyNotice: vi.fn<() => Promise<Notice | null>>().mockResolvedValue(initial),
    restartToUpdate: vi.fn<() => Promise<void>>().mockResolvedValue(undefined),
    onReadyNoticeChanged: (notify: () => void) => {
      changes.add(notify);
      return () => {
        changes.delete(notify);
      };
    },
  };
  vi.stubGlobal('electron', { update: api });
  return { ...api, notify: () => changes.forEach((notify) => notify()) };
}

async function renderNotice() {
  render(
    <UiLanguageProvider initialLanguage="ja">
      <UpdateReadyNotice />
    </UiLanguageProvider>
  );
  await act(async () => {});
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it('stays hidden until main reports a downloaded update, then restarts to install it', async () => {
  const api = bridge(null);
  await renderNotice();
  expect(screen.queryByRole('button')).not.toBeInTheDocument();

  api.getReadyNotice.mockResolvedValue({ version: '0.2.4' });
  await act(async () => api.notify());

  const button = screen.getByRole('button', { name: '0.2.4 に更新' });
  expect(screen.getByRole('status')).toContainElement(button);
  expect(button).toHaveAttribute('title', '再起動して 0.2.4 に更新します');
  fireEvent.click(button);
  expect(api.restartToUpdate).toHaveBeenCalledTimes(1);
});

it('shows an update that finished downloading before the window opened, even without a version', async () => {
  bridge({ version: null });
  await renderNotice();

  const button = screen.getByRole('button', { name: '更新' });
  expect(button).toHaveAttribute('title', '再起動して更新します');
});
