import { useMemo, type ReactNode } from 'react';

import { LocalOwnerContext } from '@/context/localOwnerContext';
import { useI18n } from '@/context/useI18n';
import { useAuth } from '@/hooks/useAuth';

/**
 * Owner scope is component lifetime.
 *
 * Everything below reads and writes data owned by one local owner. Keying the subtree on
 * the owner identity makes React drop the previous owner's state, effects and open
 * dialogs when the owner changes, so the hooks below hold one owner for their whole life
 * instead of re-checking the owner around every await. Main publishes no owner while it
 * prepares one, and none at all once the runtime is degraded, so this is also the single
 * place that says the app is not usable yet.
 *
 * Wrap only what the owner owns: a subtree that unmounts here loses whatever it was in
 * the middle of, and installation-wide settings have their own work to lose.
 */
export function LocalOwnerBoundary({
  children,
  fallback,
}: {
  children: ReactNode;
  /** Shown while there is no owner. Omit for the runtime notice; pass null for nothing. */
  fallback?: ReactNode;
}) {
  const { runtimeState } = useAuth();
  const { t } = useI18n();
  const published = runtimeState.status === 'ready' ? runtimeState.owner : null;
  const ownerId = published?.id ?? null;
  const ownerKind = published?.kind ?? null;
  // One identity per owner: main republishes its state on every auth change, and an
  // unchanged owner must not re-render the subtree that reads it.
  const owner = useMemo(
    () => (ownerId === null || ownerKind === null ? null : { id: ownerId, kind: ownerKind }),
    [ownerId, ownerKind]
  );

  if (owner === null) {
    if (fallback !== undefined) return <>{fallback}</>;
    if (runtimeState.status === 'degraded') {
      // Its own element, so the alert is inserted with its text and gets announced, and an
      // error the user has to read is not drawn in the muted color of a placeholder.
      return (
        <div key="unavailable" className="history-error" role="alert">
          {t('history.error.runtimeUnavailable')}
        </div>
      );
    }
    return (
      <div key="waiting" className="history-loading">
        {t('common.loading')}
      </div>
    );
  }

  return (
    <LocalOwnerContext.Provider key={`${owner.kind}:${owner.id}`} value={owner}>
      {children}
    </LocalOwnerContext.Provider>
  );
}
