type ScreenPoint = {
  x: number;
  y: number;
};

type CursorScreen = {
  getCursorScreenPoint: () => ScreenPoint;
};

type OverlayActivationApi = {
  isVisibleOverlayAtPoint?: (point: ScreenPoint) => boolean;
  hasRecentOverlayInteraction?: (referenceMs?: number) => boolean;
};

type Timer = ReturnType<typeof setTimeout>;

export type OverlayAwareActivateHandler = {
  handleActivate: (restoreMainWindow: () => void) => void;
};

export function createOverlayAwareActivateHandler(params: {
  overlay: OverlayActivationApi;
  screen: CursorScreen;
  now?: () => number;
  setTimer?: (callback: () => void, delayMs: number) => Timer;
  clearTimer?: (timer: Timer) => void;
  interactionWaitMs?: number;
}): OverlayAwareActivateHandler {
  const now = params.now ?? (() => Date.now());
  const setTimer = params.setTimer ?? ((callback, delayMs) => setTimeout(callback, delayMs));
  const clearTimer = params.clearTimer ?? ((timer) => clearTimeout(timer));
  const interactionWaitMs = params.interactionWaitMs ?? 80;
  let pendingTimer: Timer | null = null;

  function isCursorOverOverlay(): boolean {
    const isVisibleOverlayAtPoint = params.overlay.isVisibleOverlayAtPoint;
    if (typeof isVisibleOverlayAtPoint !== 'function') return false;
    return isVisibleOverlayAtPoint(params.screen.getCursorScreenPoint());
  }

  function hasRecentOverlayInteraction(referenceMs?: number): boolean {
    const hasRecentInteraction = params.overlay.hasRecentOverlayInteraction;
    return typeof hasRecentInteraction === 'function' && hasRecentInteraction(referenceMs);
  }

  function restoreUnlessOverlayInteraction(
    restoreMainWindow: () => void,
    referenceMs?: number
  ): void {
    if (hasRecentOverlayInteraction(referenceMs)) return;
    restoreMainWindow();
  }

  function cancelPendingRestore(): void {
    if (!pendingTimer) return;
    clearTimer(pendingTimer);
    pendingTimer = null;
  }

  return {
    handleActivate: (restoreMainWindow) => {
      cancelPendingRestore();
      const referenceMs = now();
      if (hasRecentOverlayInteraction(referenceMs)) {
        return;
      }

      try {
        if (!isCursorOverOverlay()) {
          restoreMainWindow();
          return;
        }
      } catch {
        restoreMainWindow();
        return;
      }

      pendingTimer = setTimer(() => {
        pendingTimer = null;
        restoreUnlessOverlayInteraction(restoreMainWindow, referenceMs);
      }, interactionWaitMs);
    },
  };
}
