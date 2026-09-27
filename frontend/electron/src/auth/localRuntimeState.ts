export type LocalRuntimeStatus = 'unknown' | 'syncing' | 'ready' | 'degraded';

export type LocalOwner = {
  id: string;
  kind: 'guest' | 'account';
};

export type LocalRuntimeState = {
  status: LocalRuntimeStatus;
  message: string | null;
  /** Null while configuration or the previous owner's cleanup is in progress. */
  owner: LocalOwner | null;
};

export const INITIAL_LOCAL_RUNTIME_STATE: LocalRuntimeState = {
  status: 'unknown',
  message: null,
  owner: null,
};

export function createLocalRuntimeState(
  status: Exclude<LocalRuntimeStatus, 'ready'>,
  message: string | null = null
): LocalRuntimeState {
  return {
    status,
    message: typeof message === 'string' && message.trim() ? message.trim() : null,
    owner: null,
  };
}
