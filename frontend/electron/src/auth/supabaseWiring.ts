/**
 * Supabase session wiring（main SSOT）
 *
 * 目的:
 * - `electron/src/main.ts` から Supabase session の初期化/状態反映（token/orchestration/realtime）を切り出し、
 *   main の肥大化を防ぐ。
 * - 「rendererへ token を渡さない」方針のもと、main 内で必要な派生状態（cloud token / local owner）を管理する。
 */

import type { AuthState } from '../ipc/context';
import type {
  AuthContextChangePayload,
  LocalBackendContainmentResult,
} from './localBackendAuthContextController';
import type { LocalConnectionStatus } from './localBackendSessionSync';
import type {
  RuntimeConfigLike,
  SupabaseSessionInitializationStatus,
  SupabaseSessionState,
  SupabaseSessionManagerLike,
} from './contracts';
import {
  createLocalRuntimeState,
  INITIAL_LOCAL_RUNTIME_STATE,
  type LocalRuntimeState,
  type LocalOwner,
} from './localRuntimeState';

type SupabaseSessionManagerCtor = new (opts: unknown) => SupabaseSessionManagerLike;

type TimerHandle = ReturnType<typeof setTimeout>;
type TimerApi = {
  setTimeout: (callback: () => void, delayMs: number) => TimerHandle;
  clearTimeout: (handle: TimerHandle) => void;
};

type AuthSnapshot = {
  state: SupabaseSessionState;
  context: AuthContextChangePayload;
};

type LocalConnectionStatusView = Pick<
  LocalConnectionStatus,
  'configured' | 'activeOwnerId' | 'cloudSessionState' | 'helperInstanceId'
>;

const LOCAL_RUNTIME_RETRY_DELAY_MS = 3_000;

export type SupabaseWiring = {
  initialize: () => Promise<void>;
  signOut: () => Promise<void>;
  getSessionManager: () => SupabaseSessionManagerLike | null;
  getLocalOwnerId: () => string | null;
  getRuntimeState: () => LocalRuntimeState;
  reportRuntimeUnavailable: () => void;
  getInitializationStatus: () => SupabaseSessionInitializationStatus;
};

export function createSupabaseWiring(params: {
  accountLoginEnabled: boolean;
  createClient: (url: string, key: string, options?: unknown) => unknown;
  SupabaseSessionManager: SupabaseSessionManagerCtor;
  runtimeConfig: RuntimeConfigLike | null;
  safeStorage: unknown;
  userDataDir: string;
  extractUserIdFromJwt: (token: unknown) => string | null;
  onAuthStateBroadcast: (state: AuthState) => void;
  onAuthTokenChanged?: (token: string | null) => void;
  beforeOwnerChanged: () => Promise<void>;
  onLocalOwnerChanged: (owner: LocalOwner) => void;
  onAuthContextChanged: (payload: AuthContextChangePayload) => Promise<void> | void;
  clearForSignOut: () => Promise<LocalBackendContainmentResult>;
  getLocalConnectionStatus: () => Promise<LocalConnectionStatusView>;
  onLoginStatePersist: (isLoggedIn: boolean) => void;
  onOrchestrationDisconnect: () => void;
  onOrchestrationReconnect: () => void;
  timers?: TimerApi;
}): SupabaseWiring {
  const timers = params.timers ?? {
    setTimeout: (callback: () => void, delayMs: number) => setTimeout(callback, delayMs),
    clearTimeout: (handle: TimerHandle) => clearTimeout(handle),
  };
  let sessionManager: SupabaseSessionManagerLike | null = null;
  let currentAuthToken: string | null = null;
  let runtimeState: LocalRuntimeState = INITIAL_LOCAL_RUNTIME_STATE;
  let initializationStatus: SupabaseSessionInitializationStatus = 'initializing';
  let authStateApplyQueue = Promise.resolve();
  let scheduledRetryHandle: TimerHandle | null = null;
  let latestSnapshot: AuthSnapshot | null = null;
  let syncedContext: AuthContextChangePayload | null = null;
  let ownerNeedingCleanup: LocalOwner | null = null;
  let featureOwner: LocalOwner | null = null;
  // 6.3: ローカル API トークンと所有者に束縛された WebSocket は helper の寿命で切れる。
  // 確認済み owner はそれを答えた helper とセットでしか有効でない。
  let ownerHelperInstanceId: string | null = null;
  // 同期に失敗している間は helper の認識が分からないので、次の適用で必ず送り直す。
  let authContextUnsynchronized = false;

  function setRuntimeState(nextState: LocalRuntimeState): void {
    runtimeState = nextState;
  }

  function clearScheduledRetry(): void {
    if (scheduledRetryHandle === null) {
      return;
    }
    timers.clearTimeout(scheduledRetryHandle);
    scheduledRetryHandle = null;
  }

  function scheduleRuntimeRetry(): void {
    if (scheduledRetryHandle !== null) {
      return;
    }
    scheduledRetryHandle = timers.setTimeout(() => {
      scheduledRetryHandle = null;
      if (latestSnapshot) void enqueueAuthStateApply(latestSnapshot, true);
    }, LOCAL_RUNTIME_RETRY_DELAY_MS);
  }

  async function degradeRuntime(message: string): Promise<void> {
    authContextUnsynchronized = true;
    setRuntimeState(createLocalRuntimeState('degraded', message));
    await runEffectSafely('Failed to disconnect orchestration runtime:', () => {
      params.onOrchestrationDisconnect();
    });
    // The helper needs its configuration even while signed out.
    scheduleRuntimeRetry();
  }

  function buildAuthStateSnapshot(state: SupabaseSessionState | null | undefined): AuthState {
    const isLoggedIn = Boolean((state as { isLoggedIn?: unknown } | null)?.isLoggedIn);
    return {
      authStatus: state?.authStatus ?? (isLoggedIn ? 'authenticated' : 'unauthenticated'),
      isLoggedIn,
      user: state?.user ?? null,
      runtimeState,
    };
  }

  async function invalidateLocalOwner(state: SupabaseSessionState | undefined): Promise<void> {
    // Notify every renderer before cleanup waits. Keep the old runtime ready only
    // for source-cleanup HTTP; owner-scoped operations already reject null.
    setRuntimeState({ ...runtimeState, owner: null });
    await runEffectSafely('Failed to broadcast auth state:', () => {
      params.onAuthStateBroadcast(buildAuthStateSnapshot(state));
    });
  }

  function sameOwner(left: LocalOwner | null, right: LocalOwner | null): boolean {
    return left?.id === right?.id && left?.kind === right?.kind;
  }

  function ownerOf(status: LocalConnectionStatusView): LocalOwner {
    return {
      id: status.activeOwnerId,
      kind: status.cloudSessionState === 'absent' ? 'guest' : 'account',
    };
  }

  /**
   * 6.3: the local API token and the owner-bound socket belong to the helper that
   * confirmed the owner, so a held owner survives only while that helper answers for it.
   */
  function holdsOwner(status: LocalConnectionStatusView, owner: LocalOwner): boolean {
    return (
      status.configured &&
      status.helperInstanceId === ownerHelperInstanceId &&
      sameOwner(owner, ownerOf(status))
    );
  }

  async function confirmHeldOwner(owner: LocalOwner): Promise<boolean> {
    try {
      return holdsOwner(await params.getLocalConnectionStatus(), owner);
    } catch (error) {
      // A helper that cannot answer holds nothing. The ordinary path restarts it.
      console.error('Failed to confirm the held local owner:', error);
      return false;
    }
  }

  async function releaseOwnerScope(): Promise<void> {
    params.onOrchestrationDisconnect();
    featureOwner = null;
    await params.beforeOwnerChanged();
    ownerNeedingCleanup = null;
  }

  function buildSignedOutSessionState(): SupabaseSessionState {
    return {
      authStatus: 'unauthenticated',
      isLoggedIn: false,
      user: null,
    };
  }

  async function runEffectSafely(label: string, effect: () => Promise<void> | void): Promise<void> {
    try {
      await effect();
    } catch (error) {
      console.error(label, error);
    }
  }

  function captureAuthSnapshot(state: SupabaseSessionState): AuthSnapshot {
    const token = sessionManager?.getAccessToken?.() || null;
    const expiredIdentity =
      state.authStatus === 'expired' ? (sessionManager?.getExpiredCloudIdentity?.() ?? null) : null;
    return {
      state: { ...state, user: state.user ? { ...state.user } : null },
      context: {
        token,
        userId: state.user?.id || params.extractUserIdFromJwt(token),
        sessionVersion: token ? (sessionManager?.getDesktopSessionVersion?.() ?? null) : null,
        expiredIdentity: expiredIdentity ? { ...expiredIdentity } : null,
      },
    };
  }

  async function applyAuthStateToRuntime(
    snapshot: AuthSnapshot,
    forceAuthContextSync: boolean
  ): Promise<void> {
    // A queued login must not restore credentials after a newer sign-out event.
    if (snapshot !== latestSnapshot) return;
    const { state, context } = snapshot;
    const prevToken = currentAuthToken;
    const nextToken = context.token;
    const nextAccountId = context.userId ?? context.expiredIdentity?.userId ?? null;

    // 6.2 defines the cloud identity as the account and its session version. The last
    // synced context can only be compared while that sync is known to have succeeded.
    const sameCloudIdentity =
      !authContextUnsynchronized &&
      syncedContext !== null &&
      syncedContext.userId === context.userId &&
      syncedContext.sessionVersion === context.sessionVersion &&
      syncedContext.expiredIdentity?.userId === context.expiredIdentity?.userId &&
      syncedContext.expiredIdentity?.sessionVersion === context.expiredIdentity?.sessionVersion;
    // 6.2 / 7.2: an access token refreshed for the same cloud identity is replaced without
    // stopping, so renderers keep the owner they hold instead of losing owner-scoped state
    // every refresh. Any other transition can change the owner or the effective route.
    let heldOwner =
      sameCloudIdentity && runtimeState.status === 'ready' ? runtimeState.owner : null;
    // Confirm the helper before the sync below can respawn one: an unconfigured helper
    // answers owner-less requests as its guest owner, and the runtime must not be
    // published as ready for the held owner while that is what a request would reach.
    if (heldOwner && !(await confirmHeldOwner(heldOwner))) heldOwner = null;
    if (snapshot !== latestSnapshot) return;
    if (!heldOwner) {
      await invalidateLocalOwner(state);
      if (
        ownerNeedingCleanup &&
        (ownerNeedingCleanup.kind === 'guest'
          ? nextAccountId !== null
          : ownerNeedingCleanup.id !== nextAccountId)
      ) {
        await releaseOwnerScope();
      }
      if (snapshot !== latestSnapshot) return;
      setRuntimeState(createLocalRuntimeState('syncing'));
    }

    currentAuthToken = nextToken;

    if (prevToken !== currentAuthToken) {
      await runEffectSafely('Failed to publish auth token change:', () => {
        params.onAuthTokenChanged?.(currentAuthToken);
      });
    }
    await runEffectSafely('Failed to persist login state:', () => {
      params.onLoginStatePersist(Boolean((state as { isLoggedIn?: unknown } | null)?.isLoggedIn));
    });
    await runEffectSafely('Failed to broadcast auth state:', () => {
      params.onAuthStateBroadcast(buildAuthStateSnapshot(state));
    });
    // What the renderers hold, so a later broadcast is skipped only when nothing changed.
    let broadcastRuntimeState = runtimeState;

    const shouldSyncAuthContext =
      forceAuthContextSync || !sameCloudIdentity || syncedContext?.token !== context.token;
    if (snapshot !== latestSnapshot) return;
    let nextLocalOwner: LocalOwner | null = null;
    try {
      if (shouldSyncAuthContext) {
        await params.onAuthContextChanged(context);
        // The helper has changed even if a newer event arrived during the request.
        syncedContext = context;
      }
      if (snapshot !== latestSnapshot) return;
      const status = await params.getLocalConnectionStatus();
      if (snapshot !== latestSnapshot) return;
      if (!status.configured) throw new Error('Local backend configuration is incomplete.');
      const confirmedOwner = ownerOf(status);
      if (heldOwner && !holdsOwner(status, heldOwner)) {
        // The helper changed under an apply that started out holding its owner. Stop
        // publishing the held owner and take the ordinary switch path from here.
        heldOwner = null;
        await invalidateLocalOwner(state);
        await releaseOwnerScope();
        if (snapshot !== latestSnapshot) return;
        setRuntimeState(createLocalRuntimeState('syncing'));
        broadcastRuntimeState = runtimeState;
      }
      if (!sameOwner(featureOwner, confirmedOwner)) {
        // A failed consumer may have changed only part of its scope. A later apply
        // must prepare the whole scope again, even if it returns to the old owner.
        featureOwner = null;
        params.onLocalOwnerChanged(confirmedOwner);
        featureOwner = confirmedOwner;
      }
      nextLocalOwner = confirmedOwner;
      ownerHelperInstanceId = status.helperInstanceId;
      authContextUnsynchronized = false;
    } catch (error) {
      console.error('Failed to sync local backend auth context:', error);
      await degradeRuntime(error instanceof Error ? error.message : String(error));
    }

    if (snapshot !== latestSnapshot) return;
    if (nextLocalOwner) {
      clearScheduledRetry();
      ownerNeedingCleanup = nextLocalOwner;
      if (!heldOwner) {
        // A held owner keeps its runtime state object, which in-flight main requests
        // compare by identity, and its socket: the orchestration URL and local API
        // token are owner-scoped, so a token refresh has nothing to reconnect.
        setRuntimeState({ status: 'ready', message: null, owner: nextLocalOwner });
        await runEffectSafely('Failed to reconnect orchestration runtime:', () => {
          params.onOrchestrationReconnect();
        });
      }
    }

    if (snapshot !== latestSnapshot) return;
    const runtimeStateChanged =
      runtimeState.status !== broadcastRuntimeState.status ||
      runtimeState.message !== broadcastRuntimeState.message;
    if (runtimeStateChanged) {
      await runEffectSafely('Failed to broadcast auth state:', () => {
        params.onAuthStateBroadcast(buildAuthStateSnapshot(state));
      });
    }
  }

  function enqueueAuthStateApply(
    snapshot: AuthSnapshot,
    forceAuthContextSync = false
  ): Promise<void> {
    latestSnapshot = snapshot;
    const apply = async () => {
      try {
        await applyAuthStateToRuntime(snapshot, forceAuthContextSync);
      } catch (error) {
        console.error('Failed to apply authentication transition:', error);
        await degradeRuntime(error instanceof Error ? error.message : String(error));
        await runEffectSafely('Failed to broadcast auth state:', () => {
          params.onAuthStateBroadcast(buildAuthStateSnapshot(latestSnapshot?.state));
        });
      }
    };
    authStateApplyQueue = authStateApplyQueue.then(apply, apply);
    return authStateApplyQueue;
  }

  function signOut(): Promise<void> {
    const clear = async () => {
      clearScheduledRetry();
      try {
        await invalidateLocalOwner(latestSnapshot?.state);
        await releaseOwnerScope();
        setRuntimeState(createLocalRuntimeState('syncing'));
        await runEffectSafely('Failed to broadcast auth state:', () => {
          params.onAuthStateBroadcast(buildAuthStateSnapshot(latestSnapshot?.state));
        });
        const result = await params.clearForSignOut();
        if (!result.contained) {
          throw new Error(
            `Failed to contain local helper auth context before sign-out: ${result.reason}`
          );
        }
        await sessionManager?.signOut?.();
        // Some managers emit no event when already signed out. Always reconcile,
        // without awaiting our own queue from inside the operation holding it.
        void enqueueAuthStateApply(
          captureAuthSnapshot(sessionManager?.getState?.() ?? buildSignedOutSessionState()),
          true
        );
      } catch (error) {
        await degradeRuntime(error instanceof Error ? error.message : String(error));
        await runEffectSafely('Failed to broadcast auth state:', () => {
          params.onAuthStateBroadcast(buildAuthStateSnapshot(latestSnapshot?.state));
        });
        throw error;
      }
    };
    const result = authStateApplyQueue.then(clear, clear);
    authStateApplyQueue = result.then(
      () => undefined,
      () => undefined
    );
    return result;
  }

  function reportRuntimeUnavailable(): void {
    const report = async () => {
      await degradeRuntime('Local backend runtime is unavailable.');
      await runEffectSafely('Failed to broadcast auth state:', () => {
        params.onAuthStateBroadcast(buildAuthStateSnapshot(latestSnapshot?.state));
      });
    };
    // Serialize with auth application so an in-flight successful apply cannot hide this failure.
    authStateApplyQueue = authStateApplyQueue.then(report, report);
    void authStateApplyQueue.catch((error) => {
      console.error('Failed to report local runtime unavailability:', error);
    });
  }

  async function initialize(): Promise<void> {
    initializationStatus = 'initializing';
    if (!params.accountLoginEnabled) {
      initializationStatus = 'ready';
      await enqueueAuthStateApply(captureAuthSnapshot(buildSignedOutSessionState()), true);
      return;
    }
    try {
      const supabaseUrl = params.runtimeConfig
        ? String(params.runtimeConfig.supabase_url || '').trim()
        : '';
      const supabaseKey = params.runtimeConfig
        ? String(params.runtimeConfig.supabase_publishable_key || '').trim()
        : '';
      const nextSessionManager = new params.SupabaseSessionManager({
        createClient: params.createClient,
        supabaseUrl,
        supabaseAnonKey: supabaseKey,
        userDataDir: params.userDataDir,
        safeStorage: params.safeStorage,
        extractUserIdFromJwt: params.extractUserIdFromJwt,
        logger: console,
      });

      await nextSessionManager.initialize?.();
      sessionManager = nextSessionManager;
      initializationStatus = 'ready';
      // Subscribe before the first helper request: login may finish while it is pending.
      nextSessionManager.onStateChanged?.((state: SupabaseSessionState) => {
        void enqueueAuthStateApply(captureAuthSnapshot(state));
      });
      await enqueueAuthStateApply(
        captureAuthSnapshot(nextSessionManager.getState?.() ?? buildSignedOutSessionState()),
        true
      );
    } catch (e) {
      sessionManager = null;
      initializationStatus = 'failed';
      await enqueueAuthStateApply(captureAuthSnapshot(buildSignedOutSessionState()), true);
      console.error('Failed to initialize SupabaseSessionManager:', e);
    }
  }

  return {
    initialize,
    signOut,
    reportRuntimeUnavailable,
    getSessionManager: () => sessionManager,
    getLocalOwnerId: () =>
      runtimeState.status === 'ready' ? (runtimeState.owner?.id ?? null) : null,
    getRuntimeState: () => runtimeState,
    getInitializationStatus: () => initializationStatus,
  };
}
