import { Plus, RefreshCw, Trash2 } from 'lucide-react';
import { useLayoutEffect, useState } from 'react';

import type { ConversationHistoryListItem } from '../../electron/src/history/historyContracts';
import { HistoryDeleteDialog } from '@/components/history/HistoryDeleteDialog';
import HistorySearchField from '@/components/history/HistorySearchField';
import { getConversationHistoryStatusMeta } from '@/components/history/statusTokens';
import { ShortcutHint, ShortcutKeycaps } from '@/components/shortcut/ShortcutHint';
import {
  useGlobalShortcutHint,
  type ShortcutHintState,
} from '@/components/shortcut/useGlobalShortcutHint';
import { useI18n } from '@/context/useI18n';
import { itemIdentity, useSuggestionHistory } from '@/hooks/useSuggestionHistory';
import type { MessageKey } from '@/i18n/types';

import './suggestionHistoryPage.css';

const NEW_CONVERSATION_BUTTON_ID = 'history-new-conversation';
const openButtonId = (identity: string) => `history-open:${identity}`;
const deleteButtonId = (identity: string) => `history-delete:${identity}`;

/**
 * A running or approval-waiting conversation is one whose own run the backend refuses to delete
 * (409 `CONVERSATION_BUSY`). A Suggestion's `approval_pending` only waits for the user's answer.
 */
function isDeleteBlocked(item: ConversationHistoryListItem): boolean {
  return item.kind === 'conversation' && item.status !== 'idle';
}

function deleteFailureMessageKey(errorCode: string | null): MessageKey {
  if (errorCode === 'CONVERSATION_BUSY') return 'history.delete.busy';
  if (errorCode === 'AUTHENTICATION_REQUIRED') return 'history.error.authenticationRequired';
  return 'history.delete.failed';
}

async function deleteHistoryItem(item: ConversationHistoryListItem): Promise<MessageKey | null> {
  const deleteItem = window.electron?.history?.deleteItem;
  if (!deleteItem) throw new Error('History delete bridge is unavailable.');
  const result = await deleteItem(
    item.kind === 'conversation'
      ? { kind: 'conversation', id: item.action_id }
      : { kind: 'suggestion', id: item.suggestion_id }
  );
  return result.ok ? null : deleteFailureMessageKey(result.errorCode);
}

function openSuggestionHistory(suggestionId: string): void {
  const showHistory = window.electron?.agentOverlay?.showHistory;
  if (!showHistory) throw new Error('Suggestion history overlay bridge is unavailable.');
  showHistory({ suggestionId, initialUiState: { expand: true }, fromStart: true });
}

async function openConversation(actionId: string): Promise<void> {
  const open = window.electron?.history?.openConversation;
  if (!open) throw new Error('Conversation overlay bridge is unavailable.');
  await open({ actionId });
}

async function openNewConversation(): Promise<void> {
  const open = window.electron?.history?.openNewConversation;
  if (!open) throw new Error('New conversation bridge is unavailable.');
  await open();
}

/**
 * Points at the header button, naming the shortcut only while it is registered. The sentence stays
 * one translatable string; `{shortcut}` marks where the keycaps replace it.
 */
function EmptyStateHint({
  state,
  t,
}: {
  state: ShortcutHintState;
  t: (key: MessageKey, vars?: Record<string, string | number>) => string;
}) {
  if (state.status !== 'ready')
    return <p className="history-empty-hint">{t('history.empty.startWithButton')}</p>;
  const [before, after] = t('history.empty.startWithShortcut').split('{shortcut}');
  return (
    <p className="history-empty-hint">
      {before}
      <ShortcutKeycaps accelerator={state.accelerator} t={t} />
      {after}
    </p>
  );
}

const SuggestionHistoryPage = () => {
  const {
    items,
    loading,
    loadingMore,
    error,
    isRealtimeSyncing,
    searchText,
    setSearchText,
    refresh,
    loadMore,
    hasMore,
    isUnread,
    removeItem,
  } = useSuggestionHistory();
  const { t, formatDateTime } = useI18n();
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState<ConversationHistoryListItem | null>(
    null
  );
  const [deletingIdentity, setDeletingIdentity] = useState<string | null>(null);
  const [focusTargetId, setFocusTargetId] = useState<string | null>(null);
  const shortcutHint = useGlobalShortcutHint();
  useLayoutEffect(() => {
    if (focusTargetId === null) return;
    document.getElementById(focusTargetId)?.focus();
    setFocusTargetId(null);
  }, [focusTargetId]);

  const cancelDelete = (): void => {
    if (confirmingDelete) setFocusTargetId(deleteButtonId(itemIdentity(confirmingDelete)));
    setConfirmingDelete(null);
  };
  const confirmDelete = async (): Promise<void> => {
    const item = confirmingDelete;
    if (!item) return;
    const identity = itemIdentity(item);
    const identities = items.map(itemIdentity);
    const index = identities.indexOf(identity);
    const successor = identities[index + 1] ?? identities[index - 1];
    setConfirmingDelete(null);
    setDeletingIdentity(identity);
    setNotice(null);
    let failureKey: MessageKey | null;
    try {
      failureKey = await deleteHistoryItem(item);
    } catch {
      failureKey = 'history.delete.failed';
    } finally {
      setDeletingIdentity(null);
    }
    if (failureKey !== null) {
      setNotice(t(failureKey));
      setFocusTargetId(deleteButtonId(identity));
      return;
    }
    removeItem(identity);
    setFocusTargetId(successor ? openButtonId(successor) : NEW_CONVERSATION_BUTTON_ID);
  };
  const handleNewConversation = async (): Promise<void> => {
    setNotice(null);
    try {
      await openNewConversation();
    } catch {
      setNotice(t('history.openOverlayFailed'));
    }
  };
  const handleConversation = async (actionId: string): Promise<void> => {
    setNotice(null);
    try {
      await openConversation(actionId);
    } catch {
      setNotice(t('history.openOverlayFailed'));
    }
  };
  const renderContent = () => {
    if (loading) return <div className="history-loading">{t('history.loading')}</div>;
    if (error && items.length === 0)
      return (
        <div className="history-error" role="alert">
          {error}
        </div>
      );
    if (items.length === 0) {
      return (
        <div className="history-empty">
          <span>{t('history.empty')}</span>
          <EmptyStateHint state={shortcutHint} t={t} />
        </div>
      );
    }

    return (
      <div className="history-list">
        {items.map((item) => {
          const identity =
            item.kind === 'conversation'
              ? `conversation:${item.action_id}`
              : `suggestion:${item.suggestion_id}`;
          const statusMeta = getConversationHistoryStatusMeta(item.status);
          const content = (
            <div className="history-item-body">
              <div className="history-item-text">
                <p className="history-item-title">{item.title}</p>
                <div className="history-item-meta">
                  <span>{formatDateTime(new Date(item.updated_at))}</span>
                </div>
              </div>
              <div className="history-item-status">
                {isUnread(item) ? <span aria-label={t('history.unread')}>●</span> : null}
                {statusMeta ? (
                  <span className={`badge badge--${statusMeta.tone}`}>
                    {t(statusMeta.labelKey)}
                  </span>
                ) : null}
              </div>
            </div>
          );

          return (
            <div key={identity} className="history-item">
              <button
                type="button"
                id={openButtonId(identity)}
                className="history-item-button"
                onClick={() => {
                  if (item.kind === 'conversation') {
                    void handleConversation(item.action_id);
                    return;
                  }
                  setNotice(null);
                  try {
                    openSuggestionHistory(item.suggestion_id);
                  } catch {
                    setNotice(t('history.openOverlayFailed'));
                  }
                }}
              >
                {content}
              </button>
              <button
                type="button"
                id={deleteButtonId(identity)}
                className="history-item-delete"
                aria-label={`${t('common.delete')} ${item.title}`}
                title={t('common.delete')}
                aria-busy={deletingIdentity === identity}
                disabled={isDeleteBlocked(item) || deletingIdentity !== null}
                onClick={() => setConfirmingDelete(item)}
              >
                <Trash2 size={16} aria-hidden="true" />
              </button>
            </div>
          );
        })}
        {error ? (
          <div className="history-error" role="alert">
            {error}
          </div>
        ) : null}
        {hasMore ? (
          <button
            type="button"
            className="history-filter-button"
            disabled={loadingMore || isRealtimeSyncing}
            onClick={() => void loadMore()}
          >
            {loadingMore ? t('history.loadingMore') : t('history.loadMore')}
          </button>
        ) : null}
      </div>
    );
  };

  return (
    <div className="history-container">
      <div className="history-header">
        <div className="history-toolbar">
          <HistorySearchField searchText={searchText} onSearch={setSearchText} />
          <button
            type="button"
            className="history-toolbar__icon-button"
            aria-label={t('history.reload')}
            title={t('history.reload')}
            onClick={() => void refresh()}
          >
            <RefreshCw size={16} aria-hidden="true" />
          </button>
          <ShortcutHint state={shortcutHint} t={t} />
          <button
            type="button"
            id={NEW_CONVERSATION_BUTTON_ID}
            className="history-new-conversation-button"
            onClick={() => void handleNewConversation()}
          >
            <Plus size={16} aria-hidden="true" />
            {t('history.newConversation')}
          </button>
        </div>
        {isRealtimeSyncing ? <div className="history-sync">{t('history.syncing')}</div> : null}
        {notice ? (
          <div className="history-error" role="alert">
            {notice}
          </div>
        ) : null}
      </div>
      {renderContent()}
      {confirmingDelete ? (
        <HistoryDeleteDialog t={t} onCancel={cancelDelete} onConfirm={() => void confirmDelete()} />
      ) : null}
    </div>
  );
};

export default SuggestionHistoryPage;
