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
  userTurnId,
  liveUpdate,
  paging,
  scrollRef,
  contentRef,
  answerRef,
}: {
  actionId: string | null;
  /** ID of the latest message or resume the user sent from this composer. */
  userTurnId: string | null;
  liveUpdate: Pick<ActionLiveSnapshot, 'actionId' | 'lifecycle'> | null;
  paging: ConversationPagingState;
  scrollRef: RefObject<HTMLDivElement>;
  contentRef: RefObject<HTMLDivElement>;
  answerRef: RefObject<HTMLDivElement>;
}) {
  const position = useRef({ top: 0, atBottom: true, pageCount: 1 });
  const restored = useRef(false);
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

  // The user's own send or resume shows what it started, even from a scrolled-up position.
  // Everything else, including a run that starts by itself, follows only from the bottom.
  useLayoutEffect(() => {
    if (userTurnId === null) return;
    position.current.atBottom = true;
    const scroll = scrollRef.current;
    if (scroll && restored.current && readyRef.current) scroll.scrollTop = scroll.scrollHeight;
  }, [userTurnId, scrollRef]);

  useLayoutEffect(() => {
    readyRef.current = ready;
    const scroll = scrollRef.current;
    if (!ready || !scroll) return;
    // Only a saved non-bottom position needs its complete history to restore.
    if (!restored.current && !position.current.atBottom && !historyReady) return;
    if (position.current.atBottom) {
      const item = answerRef.current?.querySelector('.action-conversation__items > li:last-child');
      const line = item?.querySelector('.action-conversation__run')?.lastElementChild;
      (line ?? item)?.scrollIntoView({ block: 'end' });
      scroll.scrollTop = scroll.scrollHeight;
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
