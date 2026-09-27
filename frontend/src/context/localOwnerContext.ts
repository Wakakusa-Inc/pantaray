import { createContext, useContext } from 'react';

import type { LocalOwner } from '../../electron/src/auth/localRuntimeState';

/** Null outside the owner boundary; inside it, the confirmed owner of that subtree. */
export const LocalOwnerContext = createContext<LocalOwner | null>(null);

/**
 * The local owner this subtree belongs to.
 *
 * `LocalOwnerBoundary` mounts a subtree only for a confirmed owner and remounts it when
 * the owner changes, so callers never see null and never have to re-check the owner
 * after an await: an owner change ends the component that started the work.
 */
export function useLocalOwner(): LocalOwner {
  const owner = useContext(LocalOwnerContext);
  if (owner === null) throw new Error('Local owner scope is unavailable.');
  return owner;
}
