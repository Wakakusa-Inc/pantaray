import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { MessageKey } from '@/i18n/types';
import { ShortcutSection } from './ShortcutSection';
const translate = (key: MessageKey) => key;
const keycapText = () =>
  [...screen.getByRole('img', { name: 'shortcut.hint.label' }).querySelectorAll('kbd')].map(
    (key) => key.textContent
  );
describe('ShortcutSection', () => {
  afterEach(() => {
    cleanup();
    delete window.electron;
  });
  it('preserves the current shortcut after a conflict and updates it after a successful retry', async () => {
    const currentState = { accelerator: 'Command+Shift+Space', failure: null } as const;
    const shortcut = {
      getState: vi.fn(async () => currentState),
      setAccelerator: vi
        .fn()
        .mockResolvedValueOnce({
          ok: false,
          reason: 'registration_unavailable',
          state: currentState,
        })
        .mockResolvedValueOnce({
          ok: true,
          state: { accelerator: 'Command+L', failure: null },
        }),
    };
    window.electron = {
      process: { platform: 'darwin' },
      shortcut,
    } as unknown as Window['electron'];

    render(<ShortcutSection t={translate} />);
    await screen.findByRole('img', { name: 'shortcut.hint.label' });
    expect(keycapText()).toEqual(['⇧', '⌘', 'Space']);
    const recordButton = screen.getByRole('button', { name: 'settings.shortcut.change' });
    fireEvent.click(recordButton);
    fireEvent.keyDown(recordButton, { key: 'k', metaKey: true });

    await screen.findByText('settings.shortcut.registrationUnavailable');
    expect(keycapText()).toEqual(['⇧', '⌘', 'Space']);
    expect(shortcut.setAccelerator).toHaveBeenNthCalledWith(1, 'Command+K');
    await waitFor(() => expect(recordButton).toHaveFocus());

    fireEvent.click(screen.getByRole('button', { name: 'settings.shortcut.change' }));
    const cancelButton = screen.getByRole('button', { name: 'settings.shortcut.cancel' });
    cancelButton.focus();
    fireEvent.click(cancelButton);
    expect(screen.getByText('settings.shortcut.registrationUnavailable')).toBeInTheDocument();
    expect(keycapText()).toEqual(['⇧', '⌘', 'Space']);
    expect(recordButton).toHaveFocus();

    fireEvent.click(recordButton);
    fireEvent.keyDown(recordButton, { key: 'l', metaKey: true });

    await waitFor(() => expect(keycapText()).toEqual(['⌘', 'L']));
    expect(screen.getByText('settings.shortcut.saved')).toBeInTheDocument();
    expect(shortcut.setAccelerator).toHaveBeenNthCalledWith(2, 'Command+L');
    await waitFor(() => expect(recordButton).toHaveFocus());
  });

  it('keeps a startup registration failure visible while recording and after cancellation', async () => {
    const startupState = {
      accelerator: 'Option+Space',
      failure: 'registration_unavailable' as const,
    };
    window.electron = {
      process: { platform: 'darwin' },
      shortcut: {
        getState: vi.fn(async () => startupState),
        setAccelerator: vi.fn(async () => ({
          ok: false as const,
          reason: 'registration_unavailable' as const,
          state: startupState,
        })),
      },
    } as unknown as Window['electron'];

    render(<ShortcutSection t={translate} />);
    const failure = await screen.findByText('settings.shortcut.initialRegistrationUnavailable');
    fireEvent.click(screen.getByRole('button', { name: 'settings.shortcut.change' }));

    expect(failure).toBeInTheDocument();
    expect(screen.getByText('settings.shortcut.recording')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'settings.shortcut.cancel' }));

    expect(failure).toBeInTheDocument();
    expect(screen.queryByText('settings.shortcut.recording')).not.toBeInTheDocument();

    const recordButton = screen.getByRole('button', { name: 'settings.shortcut.change' });
    fireEvent.click(recordButton);
    fireEvent.keyDown(recordButton, { key: 'k', metaKey: true });

    await waitFor(() => expect(failure).toBeInTheDocument());
    expect(screen.queryByText('settings.shortcut.registrationUnavailable')).not.toBeInTheDocument();
  });
});
