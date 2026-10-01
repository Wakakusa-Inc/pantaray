import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

import { UiLanguageProvider } from '@/context/UiLanguageContext';
import { RecordingRailControl } from './RecordingRailControl';

function CurrentLocation() {
  const location = useLocation();
  return <output aria-label="location">{`${location.pathname}${location.search}`}</output>;
}

function renderControl(language: 'ja' | 'en') {
  return render(
    <UiLanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={['/history']}>
        <RecordingRailControl />
        <Routes>
          <Route path="*" element={<CurrentLocation />} />
        </Routes>
      </MemoryRouter>
    </UiLanguageProvider>
  );
}

function railButton() {
  return screen.getByRole('button', { name: /コンピューター操作の記録/ });
}

function openPopover() {
  fireEvent.click(railButton());
  return screen.getByRole('dialog', { name: 'コンピューター操作の記録' });
}

describe('RecordingRailControl', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    localStorage.clear();
    delete window.electron;
  });

  it('turns recording on from the history panel without any filter prerequisite', async () => {
    localStorage.setItem('pantaray_ui_language', 'ja');
    const start = vi.fn(async () => 'started');
    window.electron = {
      screenshot: {
        start,
        stop: vi.fn(async () => true),
        getStatus: vi.fn(async () => false),
        onStatusChanged: vi.fn(() => () => undefined),
      },
    } as unknown as Window['electron'];

    renderControl('ja');
    openPopover();

    const toggle = await screen.findByRole('switch', { name: 'コンピューター操作の記録' });
    fireEvent.click(toggle);

    await waitFor(() => {
      expect(start).toHaveBeenCalledTimes(1);
    });
  });

  it('says suggestions are paused too while recording is paused', async () => {
    localStorage.setItem('pantaray_ui_language', 'ja');
    window.electron = {
      screenshot: {
        start: vi.fn(async () => 'started'),
        stop: vi.fn(async () => true),
        getStatus: vi.fn(async () => false),
        onStatusChanged: vi.fn(() => () => undefined),
      },
    } as unknown as Window['electron'];

    renderControl('ja');
    openPopover();

    expect(await screen.findByText('一時停止・提案も止まっています')).toBeInTheDocument();
  });

  it('shows no switch until the capture status arrives, then renders it on', async () => {
    localStorage.setItem('pantaray_ui_language', 'ja');
    let resolveStatus: (isCapturing: boolean) => void = () => undefined;
    window.electron = {
      screenshot: {
        start: vi.fn(async () => 'started'),
        stop: vi.fn(async () => true),
        getStatus: vi.fn(
          () =>
            new Promise<boolean>((resolve) => {
              resolveStatus = resolve;
            })
        ),
        onStatusChanged: vi.fn(() => () => undefined),
      },
    } as unknown as Window['electron'];

    renderControl('ja');
    openPopover();

    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
    expect(screen.getByText('状態を取得中…')).toBeInTheDocument();

    resolveStatus(true);

    const toggle = await screen.findByRole('switch', { name: 'コンピューター操作の記録' });
    expect(toggle).toHaveAttribute('aria-checked', 'true');
    expect(toggle.className).toContain('settings-toggle--on');
  });
  it('shows status failure without claiming recording is paused', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    window.electron = {
      screenshot: {
        start: vi.fn(async () => 'started'),
        stop: vi.fn(async () => true),
        getStatus: vi.fn(async () => {
          throw new Error('unavailable');
        }),
        onStatusChanged: vi.fn(() => () => undefined),
      },
    } as unknown as Window['electron'];
    renderControl('ja');
    await waitFor(() =>
      expect(railButton()).toHaveAccessibleName(
        '現在はコンピューター操作の記録を有効にできません。'
      )
    );
    openPopover();
    expect(await screen.findByRole('alert')).toHaveTextContent(
      '現在はコンピューター操作の記録を有効にできません。'
    );
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
    expect(screen.queryByText('一時停止・提案も止まっています')).not.toBeInTheDocument();
  });

  it('lights the rail only while recording is on, following status changes', async () => {
    localStorage.setItem('pantaray_ui_language', 'ja');
    let notify: (isEnabled: boolean) => void = () => undefined;
    window.electron = {
      screenshot: {
        start: vi.fn(async () => 'started'),
        stop: vi.fn(async () => true),
        getStatus: vi.fn(async () => false),
        onStatusChanged: vi.fn((callback: (isEnabled: boolean) => void) => {
          notify = callback;
          return () => undefined;
        }),
      },
    } as unknown as Window['electron'];

    renderControl('ja');

    const button = await screen.findByRole('button', { name: 'コンピューター操作の記録：オフ' });
    const light = button.querySelector('.app-recording-light');
    expect(light).not.toHaveClass('app-recording-light--on');

    act(() => notify(true));

    expect(button).toHaveAccessibleName('コンピューター操作の記録：オン');
    expect(light).toHaveClass('app-recording-light--on');
  });

  it('closes on Escape back to the rail, and the filter link opens its settings', async () => {
    localStorage.setItem('pantaray_ui_language', 'ja');
    window.electron = {
      screenshot: {
        start: vi.fn(async () => 'started'),
        stop: vi.fn(async () => true),
        getStatus: vi.fn(async () => true),
        onStatusChanged: vi.fn(() => () => undefined),
      },
    } as unknown as Window['electron'];

    renderControl('ja');
    await screen.findByRole('button', { name: 'コンピューター操作の記録：オン' });

    openPopover();
    expect(railButton()).toHaveAttribute('aria-expanded', 'true');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(railButton()).toHaveFocus();

    openPopover();
    fireEvent.click(screen.getByRole('button', { name: '記録するアプリとウェブサイト' }));
    expect(screen.getByRole('status', { name: 'location' })).toHaveTextContent(
      '/settings?section=screenshots'
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('leaves focus where the user put it while a toggle is answered', async () => {
    localStorage.setItem('pantaray_ui_language', 'ja');
    let notify: (isEnabled: boolean) => void = () => undefined;
    let finishStart: (result: string) => void = () => undefined;
    window.electron = {
      screenshot: {
        start: vi.fn(
          () =>
            new Promise<string>((resolve) => {
              finishStart = resolve;
            })
        ),
        stop: vi.fn(async () => true),
        getStatus: vi.fn(async () => false),
        onStatusChanged: vi.fn((callback: (isEnabled: boolean) => void) => {
          notify = callback;
          return () => undefined;
        }),
      },
    } as unknown as Window['electron'];

    renderControl('ja');
    await screen.findByRole('button', { name: 'コンピューター操作の記録：オフ' });
    openPopover();
    const toggle = await screen.findByRole('switch', { name: 'コンピューター操作の記録' });
    fireEvent.click(toggle);
    await waitFor(() => expect(toggle).toBeDisabled());

    const link = screen.getByRole('button', { name: '記録するアプリとウェブサイト' });
    link.focus();
    await act(async () => {
      finishStart('started');
    });
    act(() => notify(true));

    expect(toggle).toHaveAttribute('aria-checked', 'true');
    expect(link).toHaveFocus();
  });
});
