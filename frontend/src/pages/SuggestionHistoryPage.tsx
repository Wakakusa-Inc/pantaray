import { Plus } from 'lucide-react';
import { useState } from 'react';

import { HistoryCaptureControls } from '@/components/history/HistoryCaptureControls';
import HistoryFilterBar from '@/components/history/HistoryFilterBar';
import { getConversationHistoryStatusMeta } from '@/components/history/statusTokens';
import { ShortcutHint, ShortcutKeycaps } from '@/components/shortcut/ShortcutHint';
import {
  useGlobalShortcutHint,
  type ShortcutHintState,
} from '@/components/shortcut/useGlobalShortcutHint';
import { useI18n } from '@/context/useI18n';
import { useSuggestionHistory } from '@/hooks/useSuggestionHistory';
import type { MessageKey } from '@/i18n/types';

import './suggestionHistoryPage.css';

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
    filters,
    setFilters,
    refresh,
    loadMore,
    hasMore,
    isUnread,
  } = useSuggestionHistory();
  const { t, formatDateTime } = useI18n();
  const [overlayError, setOverlayError] = useState<string | null>(null);
  const shortcutHint = useGlobalShortcutHint();
  const handleNewConversation = async (): Promise<void> => {
    setOverlayError(null);
    try {
      await openNewConversation();
    } catch {
      setOverlayError(t('history.openOverlayFailed'));
    }
  };
  const handleConversation = async (actionId: string): Promise<void> => {
    setOverlayError(null);
    try {
      await openConversation(actionId);
    } catch {
      setOverlayError(t('history.openOverlayFailed'));
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
                className="history-item-button"
                onClick={() => {
                  if (item.kind === 'conversation') {
                    void handleConversation(item.action_id);
                    return;
                  }
                  setOverlayError(null);
                  try {
                    openSuggestionHistory(item.suggestion_id);
                  } catch {
                    setOverlayError(t('history.openOverlayFailed'));
                  }
                }}
              >
                {content}
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
        <div className="history-new-conversation">
          <ShortcutHint state={shortcutHint} t={t} />
          <button
            type="button"
            className="history-filter-button history-new-conversation__button"
            onClick={() => void handleNewConversation()}
          >
            <Plus size={16} aria-hidden="true" />
            {t('history.newConversation')}
          </button>
        </div>
        <HistoryFilterBar
          filters={filters}
          onFilterChange={setFilters}
          onReload={() => void refresh()}
          disabled={loading}
        />
        {isRealtimeSyncing ? <div className="history-sync">{t('history.syncing')}</div> : null}
        {overlayError ? (
          <div className="history-error" role="alert">
            {overlayError}
          </div>
        ) : null}
      </div>
      {renderContent()}
      <HistoryCaptureControls />
    </div>
  );
};

export default SuggestionHistoryPage;
