import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import type { ConversationHistoryListItem } from '../../electron/src/history/historyContracts';

import { COMMON_MESSAGES } from '@/i18n/messageCatalog/common';
import { HISTORY_MESSAGES } from '@/i18n/messageCatalog/history';
import { t as translate } from '@/i18n/translate';
import SuggestionHistoryPage from './SuggestionHistoryPage';
const mocks = vi.hoisted(() => ({
  error: 'history.error.fetchFailed' as string | null,
  itemsOverride: null as ConversationHistoryListItem[] | null,
  loading: false,
  loadMore: vi.fn(),
  markCompletionViewed: vi.fn(async () => undefined),
  setFilters: vi.fn(),
  unreadActionId: 'A1' as string | null,
}));
vi.mock('@/components/history/HistoryCaptureControls', () => ({
  HistoryCaptureControls: () => null,
}));
vi.mock('@/context/useI18n', async () => {
  const { formatDateTime } = await import('@/i18n/translate');
  return {
    useI18n: () => ({
      language: 'ja',
      t: (key: string) => key,
      formatDateTime: (date: Date) => formatDateTime('ja', date),
    }),
  };
});
vi.mock('@/hooks/useSuggestionHistory', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/hooks/useSuggestionHistory')>()),
  useSuggestionHistory: () => ({
    items: mocks.itemsOverride ?? [
      {
        kind: 'conversation',
        action_id: 'A1',
        title: 'Conversation',
        updated_at: '2026-08-30T01:02:03.000Z',
        status: 'idle',
        latest_completion_event_id: 'C1',
      },
      {
        kind: 'suggestion',
        suggestion_id: 'S1',
        title: 'Suggestion',
        updated_at: '2026-08-30T01:02:03.000Z',
        status: 'idle',
      },
    ],
    loading: mocks.loading,
    loadingMore: false,
    error: mocks.error,
    isRealtimeSyncing: false,
    filters: { status: 'all', searchText: '' },
    setFilters: mocks.setFilters,
    refresh: vi.fn(),
    loadMore: mocks.loadMore,
    hasMore: true,
    isUnread: (item: { action_id?: string }) => item.action_id === mocks.unreadActionId,
  }),
}));

afterEach(() => {
  cleanup();
  mocks.error = 'history.error.fetchFailed';
  mocks.itemsOverride = null;
  mocks.loading = false;
  mocks.unreadActionId = 'A1';
  vi.clearAllMocks();
});

it('空状態でも起動ボタンは右上の1つだけで、keyboardから開ける', async () => {
  const openNewConversation = vi.fn(async () => undefined);
  window.electron = { history: { openNewConversation } } as unknown as Window['electron'];
  const { rerender } = render(<SuggestionHistoryPage />);

  expect(HISTORY_MESSAGES.ja['history.newConversation']).toBe('新しい会話');
  expect(HISTORY_MESSAGES.en['history.newConversation']).toBe('New conversation');
  expect(screen.getAllByRole('button', { name: 'history.newConversation' })).toHaveLength(1);
  const cta = screen.getByRole('button', { name: 'history.newConversation' });
  expect(cta.closest('.history-new-conversation')).not.toBeNull();
  cta.focus();
  await userEvent.keyboard('{Enter}');
  expect(openNewConversation).toHaveBeenCalledOnce();
  expect(openNewConversation).toHaveBeenCalledWith();

  mocks.error = null;
  mocks.itemsOverride = [];
  rerender(<SuggestionHistoryPage />);
  expect(screen.getAllByRole('button', { name: 'history.newConversation' })).toHaveLength(1);
  expect(screen.getByRole('button', { name: 'history.newConversation' })).toBe(cta);
  expect(cta).toHaveFocus();
  // No shortcut bridge: the empty state points at the button alone.
  expect(screen.getByText('history.empty.startWithButton')).toBeInTheDocument();
  expect(HISTORY_MESSAGES.ja['history.empty.startWithShortcut']).toContain('{shortcut}');

  openNewConversation.mockRejectedValueOnce(new Error('unavailable'));
  await userEvent.click(cta);
  expect(await screen.findByRole('alert')).toHaveTextContent('history.openOverlayFailed');
});

it('CTAの隣に設定中のショートカットをキーキャップで表示する', async () => {
  const getState = vi.fn(async () => ({ accelerator: 'Option+Space', failure: null }));
  window.electron = {
    process: { platform: 'darwin' },
    history: { openNewConversation: vi.fn(async () => undefined) },
    shortcut: { getState },
  } as unknown as Window['electron'];
  const { container, rerender } = render(<SuggestionHistoryPage />);

  expect(screen.getByText('shortcut.hint.loading')).toBeInTheDocument();
  const keycaps = await screen.findByRole('img', { name: 'shortcut.hint.label' });
  expect([...keycaps.querySelectorAll('kbd')].map((key) => key.textContent)).toEqual([
    '⌥',
    'Space',
  ]);
  expect(keycaps.closest('.history-new-conversation')).not.toBeNull();
  expect(keycaps.nextElementSibling).toBe(
    screen.getByRole('button', { name: 'history.newConversation' })
  );
  expect(translate('ja', 'shortcut.hint.label', { keys: 'Option Space' })).toBe(
    'ショートカット: Option Space'
  );
  expect(COMMON_MESSAGES.en['shortcut.hint.label']).toBe('Shortcut: {keys}');

  mocks.error = null;
  mocks.itemsOverride = [];
  rerender(<SuggestionHistoryPage />);
  // The empty state names the shortcut inside the sentence instead of repeating the button.
  const hint = container.querySelector('.history-empty-hint');
  expect(hint?.querySelector('.shortcut-keycaps')).not.toBeNull();
  expect(HISTORY_MESSAGES.ja['history.empty.startWithShortcut'].split('{shortcut}')).toHaveLength(
    2
  );
  expect(HISTORY_MESSAGES.en['history.empty.startWithShortcut'].split('{shortcut}')).toHaveLength(
    2
  );
});

it('ショートカットが登録できていないときはキーキャップを出さない', async () => {
  window.electron = {
    process: { platform: 'darwin' },
    shortcut: {
      getState: vi.fn(async () => ({
        accelerator: 'Option+Space',
        failure: 'registration_unavailable',
      })),
    },
  } as unknown as Window['electron'];
  render(<SuggestionHistoryPage />);

  expect(await screen.findByText('shortcut.hint.unavailable')).toBeInTheDocument();
  expect(screen.queryByRole('img', { name: 'shortcut.hint.label' })).toBeNull();
});

it('Conversation行はOverlayを開き、実際の表示前に既読にしない', async () => {
  const openConversation = vi.fn(async () => 'created' as const);
  const showHistory = vi.fn();
  window.electron = {
    agentOverlay: { showHistory },
    history: { openConversation, markCompletionViewed: mocks.markCompletionViewed },
  } as unknown as Window['electron'];
  render(<SuggestionHistoryPage />);

  const conversation = screen.getByRole('button', { name: /^Conversation/ });
  expect(conversation).not.toHaveAttribute('aria-expanded');
  expect(screen.getByLabelText('history.unread')).toBeInTheDocument();
  expect(screen.getAllByText((text) => text.endsWith(':02'))).toHaveLength(2);
  conversation.focus();
  await userEvent.keyboard('{Enter}');
  expect(openConversation).toHaveBeenCalledWith({ actionId: 'A1' });
  expect(mocks.markCompletionViewed).not.toHaveBeenCalled();
  expect(screen.queryByRole('region', { name: 'history.detail.conversation' })).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: /Suggestion/ }));
  expect(showHistory).toHaveBeenCalledWith({
    suggestionId: 'S1',
    initialUiState: { expand: true },
    fromStart: true,
  });
});

it('履歴の取得失敗は読み上げソフトに届くalertとして出す', () => {
  window.electron = {} as unknown as Window['electron'];
  mocks.unreadActionId = null;
  const { rerender } = render(<SuggestionHistoryPage />);

  expect(screen.getByRole('alert')).toHaveTextContent('history.error.fetchFailed');

  // 1件も出せなかったときの取得失敗。
  mocks.itemsOverride = [];
  rerender(<SuggestionHistoryPage />);
  expect(screen.getByRole('alert')).toHaveTextContent('history.error.fetchFailed');
});

it('Overlay起動失敗を通知し、追加読み込みと検索に応答する', async () => {
  const openConversation = vi.fn(async () => 'focused' as const);
  window.electron = { history: { openConversation } } as unknown as Window['electron'];
  mocks.error = null;
  mocks.unreadActionId = null;
  render(<SuggestionHistoryPage />);

  await userEvent.click(screen.getByRole('button', { name: /^Conversation/ }));
  openConversation.mockRejectedValueOnce(new Error('unavailable'));
  await userEvent.click(screen.getByRole('button', { name: /^Conversation/ }));
  expect(await screen.findByRole('alert')).toHaveTextContent('history.openOverlayFailed');

  fireEvent.click(screen.getByRole('button', { name: 'history.loadMore' }));
  expect(mocks.loadMore).toHaveBeenCalledOnce();
  const search = screen.getByRole('searchbox', { name: 'history.filter.searchLabel' });
  fireEvent.change(search, { target: { value: `${'😀'.repeat(256)}x` } });
  expect(search).toHaveValue('😀'.repeat(256));
  fireEvent.click(screen.getByRole('button', { name: 'history.filter.searchButton' }));
  expect(mocks.setFilters.mock.calls[0][0]({ status: 'all', searchText: '' }).searchText).toBe(
    '😀'.repeat(256)
  );
});

it('バッジは running / approval_pending だけに出し、idle には出さない', () => {
  window.electron = {} as unknown as Window['electron'];
  mocks.error = null;
  mocks.unreadActionId = null;
  mocks.itemsOverride = [
    {
      kind: 'conversation',
      action_id: 'A-running',
      title: 'Running',
      updated_at: '2026-08-30T01:02:03.000Z',
      status: 'running',
      latest_completion_event_id: null,
    },
    {
      kind: 'conversation',
      action_id: 'A-approval',
      title: 'Approval',
      updated_at: '2026-08-30T01:02:03.000Z',
      status: 'approval_pending',
      latest_completion_event_id: null,
    },
    {
      kind: 'conversation',
      action_id: 'A-idle',
      title: 'Idle',
      updated_at: '2026-08-30T01:02:03.000Z',
      status: 'idle',
      latest_completion_event_id: null,
    },
  ];
  const { container } = render(<SuggestionHistoryPage />);

  expect([...container.querySelectorAll('.badge')].map((badge) => badge.textContent)).toEqual([
    'history.status.running',
    'history.status.approvalPending',
  ]);
});
