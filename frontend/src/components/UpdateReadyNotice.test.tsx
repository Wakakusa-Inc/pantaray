import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { UpdateReadyNotice as Notice } from '../../electron/src/ipc/context';
import { UiLanguageProvider } from '@/context/UiLanguageContext';
import { UpdateReadyNotice } from './UpdateReadyNotice';

function bridge(initial: Notice | null) {
  const changes = new Set<() => void>();
  const api = {
    getReadyNotice: vi.fn<() => Promise<Notice | null>>().mockResolvedValue(initial),
    dismissReadyNotice: vi.fn<() => Promise<void>>().mockResolvedValue(undefined),
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

it('stays hidden until main reports a downloaded update, then offers the restart', async () => {
  const api = bridge(null);
  await renderNotice();
  expect(screen.queryByRole('button')).not.toBeInTheDocument();

  api.getReadyNotice.mockResolvedValue({ version: '0.2.2' });
  await act(async () => api.notify());

  expect(screen.getByRole('status')).toHaveTextContent(
    '新しいバージョン（0.2.2）の準備ができました'
  );
  fireEvent.click(screen.getByRole('button', { name: '再起動して更新' }));
  expect(api.restartToUpdate).toHaveBeenCalledTimes(1);
});

it('shows an update that finished downloading before the window opened, and "later" hides it', async () => {
  const api = bridge({ version: null });
  await renderNotice();
  expect(screen.getByText('新しいバージョンの準備ができました')).toBeVisible();

  fireEvent.click(screen.getByRole('button', { name: 'あとで' }));

  expect(api.dismissReadyNotice).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
});
