import { useEffect, useRef, useState } from 'react';

type AuthState = Awaited<ReturnType<NonNullable<Window['electron']>['auth']['getState']>>;

/** Read receipts belong to a focused viewport containing the canonical result's end. */
export function useCompletionViewed(
  actionId: string | null,
  completionEventId: string | null,
  enabled: boolean
) {
  const endRef = useRef<HTMLDivElement>(null);
  const identity = JSON.stringify([actionId, completionEventId]);
  const [failedIdentity, setFailedIdentity] = useState<string | null>(null);

  useEffect(() => {
    const end = endRef.current;
    const auth = window.electron?.auth;
    const markViewed = window.electron?.history?.markCompletionViewed;
    if (!enabled || !actionId || !completionEventId || !end || !auth || !markViewed) return;
    let disposed = false;
    let visible = false;
    let subjectId: string | null = null;
    let authRevision = 0;
    let subjectRevision = 0;
    let readingAuth = false;
    let pending = false;
    let marked = false;
    const markIfViewed = () => {
      if (
        disposed ||
        !visible ||
        !subjectId ||
        pending ||
        marked ||
        document.visibilityState !== 'visible' ||
        !document.hasFocus()
      )
        return;
      pending = true;
      const revision = subjectRevision;
      void markViewed({ subjectId, actionId, completionEventId })
        .then(() => {
          if (disposed || revision !== subjectRevision) return;
          marked = true;
          pending = false;
          setFailedIdentity(null);
        })
        .catch(() => {
          if (disposed || revision !== subjectRevision) return;
          pending = false;
          setFailedIdentity(identity);
        });
    };
    const acceptAuth = (state: AuthState) => {
      if (disposed) return;
      const nextSubject =
        state.runtimeState.status === 'ready' ? (state.runtimeState.owner?.id ?? null) : null;
      if (subjectId !== nextSubject) {
        subjectRevision += 1;
        subjectId = nextSubject;
        pending = false;
        marked = false;
        setFailedIdentity(null);
      }
      markIfViewed();
    };
    const readAuth = () => {
      if (disposed || readingAuth) return;
      readingAuth = true;
      const revision = authRevision;
      void auth
        .getState()
        .then((state) => {
          if (!disposed && revision === authRevision) acceptAuth(state);
        })
        .catch(() => {
          if (!disposed && revision === authRevision) setFailedIdentity(identity);
        })
        .finally(() => {
          readingAuth = false;
        });
    };
    const unsubscribe = auth.onStateChanged?.((state) => {
      authRevision += 1;
      acceptAuth(state);
    });
    const foreground = () => {
      if (subjectId === null) readAuth();
      markIfViewed();
    };
    const observer = new IntersectionObserver(
      ([entry]) => {
        visible = entry.isIntersecting && entry.intersectionRatio === 1;
        markIfViewed();
      },
      { threshold: 1 }
    );
    observer.observe(end);
    window.addEventListener('focus', foreground);
    document.addEventListener('visibilitychange', foreground);
    readAuth();
    return () => {
      disposed = true;
      observer.disconnect();
      unsubscribe?.();
      window.removeEventListener('focus', foreground);
      document.removeEventListener('visibilitychange', foreground);
    };
  }, [actionId, completionEventId, enabled, identity]);

  return { endRef, failed: failedIdentity === identity };
}
