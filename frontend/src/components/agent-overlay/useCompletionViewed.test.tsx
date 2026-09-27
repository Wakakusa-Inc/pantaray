import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import { useCompletionViewed } from './useCompletionViewed';

type AuthState = Awaited<ReturnType<NonNullable<Window['electron']>['auth']['getState']>>;
const authenticated: AuthState = {
  authStatus: 'authenticated',
  isLoggedIn: true,
  user: { id: 'user-a' },
  runtimeState: { status: 'ready', message: null, owner: { kind: 'account', id: 'user-a' } },
};
let authChanged: (state: AuthState) => void;
let intersections: IntersectionObserverCallback[];
let focused: boolean;
let visibility: DocumentVisibilityState;
const getState = vi.fn<() => Promise<AuthState>>();
const markViewed = vi.fn<() => Promise<void>>();
const unsubscribe = vi.fn();
const disconnect = vi.fn();

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((accept, fail) => {
    resolve = accept;
    reject = fail;
  });
  return { promise, resolve, reject };
}
function Harness({
  event = 'completion-1',
  enabled = true,
}: {
  event?: string;
  enabled?: boolean;
}) {
  const { endRef, failed } = useCompletionViewed('action-1', event, enabled);
  return (
    <>
      <div ref={endRef} />
      <output>{failed ? 'failed' : 'ready'}</output>
    </>
  );
}
function intersect(ratio: number) {
  act(() =>
    intersections[intersections.length - 1](
      [{ isIntersecting: ratio > 0, intersectionRatio: ratio } as IntersectionObserverEntry],
      {} as IntersectionObserver
    )
  );
}
function focus() {
  focused = true;
  act(() => window.dispatchEvent(new Event('focus')));
}

beforeEach(() => {
  vi.clearAllMocks();
  getState.mockResolvedValue(authenticated);
  markViewed.mockResolvedValue(undefined);
  focused = true;
  visibility = 'visible';
  intersections = [];
  vi.spyOn(document, 'hasFocus').mockImplementation(() => focused);
  vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility);
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      constructor(callback: IntersectionObserverCallback) {
        intersections.push(callback);
      }
      observe() {}
      disconnect = disconnect;
    }
  );
  window.electron = {
    auth: {
      getState,
      onStateChanged: (callback: typeof authChanged) => {
        authChanged = callback;
        return unsubscribe;
      },
    },
    history: { markCompletionViewed: markViewed },
  } as unknown as Window['electron'];
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete window.electron;
});

it('結果の末尾が全て見え、前面になるまで既読にせず、同じ結果を重複送信しない', async () => {
  focused = false;
  render(<Harness />);
  await act(async () => {});
  intersect(1);
  expect(markViewed).not.toHaveBeenCalled();
  intersect(0.5);
  focus();
  expect(markViewed).not.toHaveBeenCalled();
  intersect(1);
  await waitFor(() =>
    expect(markViewed).toHaveBeenCalledWith({
      subjectId: 'user-a',
      actionId: 'action-1',
      completionEventId: 'completion-1',
    })
  );
  intersect(0);
  intersect(1);
  focus();
  expect(markViewed).toHaveBeenCalledOnce();
});

it('非表示・折りたたみでは既読化せず、新しい完了ごとに実際の表示を待つ', async () => {
  const { rerender } = render(<Harness enabled={false} />);
  expect(intersections).toHaveLength(0);
  rerender(<Harness />);
  await act(async () => {});
  visibility = 'hidden';
  intersect(1);
  expect(markViewed).not.toHaveBeenCalled();
  visibility = 'visible';
  await act(async () => document.dispatchEvent(new Event('visibilitychange')));
  expect(markViewed).toHaveBeenCalledOnce();
  rerender(<Harness event="completion-2" />);
  await act(async () => {});
  focus();
  expect(markViewed).toHaveBeenCalledOnce();
  intersect(1);
  await waitFor(() =>
    expect(markViewed).toHaveBeenLastCalledWith({
      subjectId: 'user-a',
      actionId: 'action-1',
      completionEventId: 'completion-2',
    })
  );
});

it('サインアウト通知の後に古い認証readが返っても既読化しない', async () => {
  const oldAuth = deferred<AuthState>();
  getState.mockReturnValueOnce(oldAuth.promise);
  render(<Harness />);
  intersect(1);
  act(() =>
    authChanged({
      ...authenticated,
      authStatus: 'unauthenticated',
      user: null,
      runtimeState: { status: 'syncing', message: null, owner: null },
    })
  );
  await act(async () => oldAuth.resolve(authenticated));
  expect(markViewed).not.toHaveBeenCalled();
});

it('保存失敗を通知し、同一ownerのready通知に妨げられず次の閲覧で再試行する', async () => {
  const write = deferred<void>();
  markViewed.mockReturnValueOnce(write.promise);
  render(<Harness />);
  await act(async () => {});
  intersect(1);
  act(() => authChanged(authenticated));
  await act(async () => write.reject(new Error('disk failure')));
  expect(screen.getByRole('status')).toHaveTextContent('failed');
  expect(markViewed).toHaveBeenCalledOnce();
  focus();
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('ready'));
  expect(markViewed).toHaveBeenCalledTimes(2);
});

it('認証取得に失敗しても前面に戻った時に再取得し、保存まで回復する', async () => {
  getState.mockRejectedValueOnce(new Error('read failure'));
  render(<Harness />);
  intersect(1);
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('failed'));
  expect(markViewed).not.toHaveBeenCalled();
  focus();
  await waitFor(() => expect(markViewed).toHaveBeenCalledOnce());
  expect(screen.getByRole('status')).toHaveTextContent('ready');
});

it('閉じた会話の認証応答やobserver通知は保存を開始しない', async () => {
  const pendingAuth = deferred<AuthState>();
  getState.mockReturnValueOnce(pendingAuth.promise);
  const { unmount } = render(<Harness />);
  intersect(1);
  unmount();
  await act(async () => pendingAuth.resolve(authenticated));
  focus();
  intersect(1);
  expect(markViewed).not.toHaveBeenCalled();
  expect(disconnect).toHaveBeenCalledOnce();
  expect(unsubscribe).toHaveBeenCalledOnce();
});

it('新しい完了の表示後に古い認証readが返っても、過去の既読を後から送らない', async () => {
  const oldAuth = deferred<AuthState>();
  getState.mockReturnValueOnce(oldAuth.promise);
  const { rerender } = render(<Harness />);
  intersect(1);
  rerender(<Harness event="completion-2" />);
  await act(async () => {});
  intersect(1);
  await waitFor(() =>
    expect(markViewed).toHaveBeenCalledWith({
      subjectId: 'user-a',
      actionId: 'action-1',
      completionEventId: 'completion-2',
    })
  );
  await act(async () => oldAuth.resolve(authenticated));
  expect(markViewed).toHaveBeenCalledOnce();
});

it.each([
  { authStatus: 'unauthenticated', kind: 'guest', id: 'guest-owner' },
  { authStatus: 'expired', kind: 'account', id: 'expired-account' },
] as const)(
  '$authStatusでも確認済み$kind ownerの既読を保存する',
  async ({ authStatus, kind, id }) => {
    getState.mockResolvedValue({
      authStatus,
      isLoggedIn: false,
      user: null,
      runtimeState: { status: 'ready', message: null, owner: { kind, id } },
    });
    render(<Harness />);
    await act(async () => {});
    intersect(1);
    await waitFor(() =>
      expect(markViewed).toHaveBeenCalledWith({
        subjectId: id,
        actionId: 'action-1',
        completionEventId: 'completion-1',
      })
    );
  }
);

it('owner不明時は既読を送らず、同じownerが戻っても古い失敗を表示しない', async () => {
  const oldWrite = deferred<void>();
  const newWrite = deferred<void>();
  markViewed.mockReturnValueOnce(oldWrite.promise).mockReturnValueOnce(newWrite.promise);
  render(<Harness />);
  await act(async () => {});
  intersect(1);
  const unavailable: AuthState = {
    ...authenticated,
    runtimeState: { status: 'ready', message: null, owner: null },
  };
  getState.mockResolvedValue(unavailable);
  act(() => authChanged(unavailable));
  focus();
  await act(async () => {});
  expect(markViewed).toHaveBeenCalledOnce();
  act(() => authChanged(authenticated));
  expect(markViewed).toHaveBeenCalledTimes(2);
  await act(async () => oldWrite.reject(new Error('Old scope failure')));
  expect(screen.getByRole('status')).toHaveTextContent('ready');
  await act(async () => newWrite.resolve());
  focus();
  expect(markViewed).toHaveBeenCalledTimes(2);
});

it('ownerが非公開になったら前の保存エラーを非表示にする', async () => {
  markViewed.mockRejectedValueOnce(new Error('Write failed'));
  render(<Harness />);
  await act(async () => {});
  intersect(1);
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('failed'));
  act(() =>
    authChanged({
      ...authenticated,
      runtimeState: { status: 'syncing', message: null, owner: null },
    })
  );
  expect(screen.getByRole('status')).toHaveTextContent('ready');
  expect(markViewed).toHaveBeenCalledOnce();
});
