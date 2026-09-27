import { useCallback, useEffect, useRef } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';

const HEADER_DRAG_EXCLUDED_SELECTOR =
  'button, a, input, textarea, select, [role="button"], [contenteditable="true"], [data-overlay-control="true"]';

type OverlayHeaderDragState = {
  pointerId: number;
};

export type OverlayHeaderDragHandlers = {
  onHeaderPointerDown: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onHeaderPointerMove: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onHeaderPointerUp: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onHeaderPointerCancel: (event: ReactPointerEvent<HTMLDivElement>) => void;
};

function isHeaderDragExcludedTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  return Boolean(target.closest(HEADER_DRAG_EXCLUDED_SELECTOR));
}

export function useOverlayHeaderDrag(): OverlayHeaderDragHandlers {
  const dragRef = useRef<OverlayHeaderDragState | null>(null);

  const endHeaderDrag = useCallback((event?: ReactPointerEvent<HTMLDivElement>) => {
    const activeDrag = dragRef.current;
    if (!activeDrag) return;
    if (event && event.pointerId !== activeDrag.pointerId) return;
    if (event) {
      try {
        event.currentTarget.releasePointerCapture(activeDrag.pointerId);
      } catch {
        // no-op
      }
    }
    dragRef.current = null;
    try {
      window.electron?.agentOverlay?.dragEnd?.();
    } catch {
      // no-op
    }
  }, []);

  useEffect(() => {
    return () => {
      try {
        window.electron?.agentOverlay?.dragEnd?.();
      } catch {
        // no-op
      }
    };
  }, []);

  const onHeaderPointerDown = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    if (isHeaderDragExcludedTarget(event.target)) return;
    const dragStart = window.electron?.agentOverlay?.dragStart;
    if (!dragStart) return;

    event.preventDefault();
    dragRef.current = { pointerId: event.pointerId };
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // no-op
    }
    dragStart({ screenX: event.screenX, screenY: event.screenY });
  }, []);

  const onHeaderPointerMove = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const activeDrag = dragRef.current;
    if (!activeDrag || event.pointerId !== activeDrag.pointerId) return;
    event.preventDefault();
    try {
      window.electron?.agentOverlay?.dragMove?.({ screenX: event.screenX, screenY: event.screenY });
    } catch {
      // no-op
    }
  }, []);

  const onHeaderPointerUp = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      endHeaderDrag(event);
    },
    [endHeaderDrag]
  );

  const onHeaderPointerCancel = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      endHeaderDrag(event);
    },
    [endHeaderDrag]
  );

  return {
    onHeaderPointerDown,
    onHeaderPointerMove,
    onHeaderPointerUp,
    onHeaderPointerCancel,
  };
}
