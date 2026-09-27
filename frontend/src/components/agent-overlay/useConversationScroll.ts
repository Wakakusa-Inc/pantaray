import { useCallback, useLayoutEffect, useRef, type RefObject } from 'react';
import type { ActionLiveSnapshot } from '../../../electron/src/actions/actionLiveCore';
import type { ConversationPagingState } from './conversationPaging';
import {
  readConversationScrollPosition,
  saveConversationScrollPosition,
} from './conversationScrollPosition';

// Scroll offsets can be fractional even though clientHeight/scrollHeight are integers.
const BOTTOM_TOLERANCE_PX = 2;

export function useConversationScroll({
  actionId,
  liveUpdate,
  paging,
  scrollRef,
  contentRef,
  answerRef,
}: {
  actionId: string | null;
  liveUpdate: Pick<ActionLiveSnapshot, 'actionId' | 'lifecycle'> | null;
  paging: ConversationPagingState;
  scrollRef: RefObject<HTMLDivElement>;
  contentRef: RefObject<HTMLDivElement>;
  answerRef: RefObject<HTMLDivElement>;
}) {
  const position = useRef({ top: 0, atBottom: true, pageCount: 1 });
  const restored = useRef(false);
  const previousPage = useRef(paging.currentPage);
  const previousUpdate = useRef(liveUpdate);
  const ready = actionId !== null && paging.pages?.[0].action.action_id === actionId;
  const historyReady = paging.olderPageState === 'idle';
  const readyRef = useRef(ready);

  const save = useCallback(() => {
    const scroll = scrollRef.current;
    if (!actionId || !scroll || !restored.current || !readyRef.current) return;
    position.current = {
      ...position.current,
      top: scroll.scrollTop,
      atBottom: scroll.scrollHeight - scroll.clientHeight - scroll.scrollTop < BOTTOM_TOLERANCE_PX,
    };
    saveConversationScrollPosition(actionId, position.current);
  }, [actionId, scrollRef]);

  useLayoutEffect(() => {
    position.current = (actionId && readConversationScrollPosition(actionId)) || {
      top: 0,
      atBottom: true,
      pageCount: 1,
    };
    restored.current = false;
    previousPage.current = null;
    previousUpdate.current = null;
    const scroll = scrollRef.current;
    const content = contentRef.current;
    if (!actionId || !scroll || !content) return;
    const observer = new ResizeObserver(() => {
      if (restored.current && readyRef.current && position.current.atBottom)
        scroll.scrollTop = scroll.scrollHeight;
    });
    observer.observe(scroll);
    observer.observe(content);
    scroll.addEventListener('scroll', save, { passive: true });
    window.addEventListener('pagehide', save);
    return () => {
      observer.disconnect();
      scroll.removeEventListener('scroll', save);
      window.removeEventListener('pagehide', save);
    };
  }, [actionId, scrollRef, contentRef, save]);

  useLayoutEffect(() => {
    readyRef.current = ready;
    const scroll = scrollRef.current;
    if (!ready || !scroll) return;
    const current = paging.currentPage;
    const previous = previousPage.current;
    // Replayed terminal snapshots must not displace a restored reading position.
    const newActivity =
      previous !== null &&
      (current !== previous || liveUpdate !== previousUpdate.current) &&
      (liveUpdate?.lifecycle?.status === 'processing' ||
        current?.action.status === 'processing' ||
        current?.action.status === 'queued' ||
        previous?.action.status === 'processing' ||
        previous?.action.status === 'queued' ||
        current?.action.latest_run_id !== previous?.action.latest_run_id);
    previousPage.current = current;
    previousUpdate.current = liveUpdate;
    // New activity takes precedence over a saved position. Without new activity,
    // only a saved non-bottom position needs its complete history to restore.
    if (!restored.current && !position.current.atBottom && !historyReady && !newActivity) return;
    const showLatest = position.current.atBottom || newActivity;
    if (showLatest) {
      const item = answerRef.current?.querySelector('.action-conversation__items > li:last-child');
      const line = item?.querySelector('.action-conversation__run')?.lastElementChild;
      (line ?? item)?.scrollIntoView({ block: 'end' });
      scroll.scrollTop = scroll.scrollHeight;
      position.current.atBottom = true;
    } else if (!restored.current) {
      scroll.scrollTop = position.current.top;
    }
    restored.current = true;
    // A partial/failed refresh must not shrink the history required by a bookmark.
    if (historyReady) {
      position.current.pageCount = paging.pages!.length;
      save();
    }
  }, [ready, historyReady, paging, liveUpdate, scrollRef, answerRef, save]);
}
