import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, expect, it, vi } from 'vitest';

import { AuthContext, type AuthContextType } from '@/context/AuthContextDef';
import { UiLanguageProvider } from '@/context/UiLanguageContext';
import { useLocalOwner } from '@/context/localOwnerContext';
import { LocalOwnerBoundary } from './LocalOwnerBoundary';

type Runtime = AuthContextType['runtimeState'];

function ready(id: string): Runtime {
  return { status: 'ready', message: null, owner: { kind: 'account', id } };
}

/** Stands for any owner-scoped page: it holds work that belongs to one owner only. */
function ScopedPage() {
  const owner = useLocalOwner();
  const [draft, setDraft] = useState('nothing typed');
  return (
    <button type="button" onClick={() => setDraft('secret note')}>
      {`${owner.kind}:${owner.id} / ${draft}`}
    </button>
  );
}

function subject(runtimeState: Runtime) {
  const auth: AuthContextType = {
    authStatus: 'authenticated',
    user: null,
    session: null,
    loading: false,
    runtimeState,
    signIn: vi.fn(async () => ({ error: null })),
    signUp: vi.fn(async () => ({ status: 'created' as const, error: null })),
    signOut: vi.fn(async () => ({ error: null })),
    resetPassword: vi.fn(async () => ({ error: null })),
  };
  return (
    <AuthContext.Provider value={auth}>
      <UiLanguageProvider initialLanguage="ja">
        <LocalOwnerBoundary>
          <ScopedPage />
        </LocalOwnerBoundary>
      </UiLanguageProvider>
    </AuthContext.Provider>
  );
}

function typeSomething() {
  fireEvent.click(screen.getByRole('button'));
}

afterEach(cleanup);

it('does not show one owner the work started under the previous owner', () => {
  const view = render(subject(ready('alice')));
  typeSomething();
  expect(screen.getByRole('button')).toHaveTextContent('account:alice / secret note');

  view.rerender(subject(ready('bob')));

  expect(screen.getByRole('button')).toHaveTextContent('account:bob / nothing typed');
});

it.each([
  { status: 'unknown', message: null, owner: null },
  { status: 'syncing', message: null, owner: null },
  // Main publishes this while it cleans up after the owner it is replacing.
  { status: 'ready', message: null, owner: null },
] satisfies Runtime[])('waits for the owner main is preparing ($status)', (runtimeState) => {
  render(subject(runtimeState));

  expect(screen.queryByRole('button')).not.toBeInTheDocument();
  expect(screen.getByText('読み込み中…')).toBeVisible();
});

it('reports an unavailable runtime instead of an owner-scoped page', () => {
  render(subject({ status: 'degraded', message: 'helper unavailable', owner: null }));

  expect(screen.getByRole('alert')).toHaveTextContent('ローカル実行基盤が利用できません。');
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
});

it('announces the unavailable runtime as a newly inserted alert', () => {
  const view = render(subject({ status: 'syncing', message: null, owner: null }));
  const waiting = screen.getByText('読み込み中…');

  view.rerender(subject({ status: 'degraded', message: 'helper unavailable', owner: null }));

  // An alert that only gains its role and text on an existing node is often not read out.
  expect(screen.getByRole('alert')).not.toBe(waiting);
  expect(waiting).not.toBeInTheDocument();
});

it('starts over when the same owner comes back from a runtime restart', () => {
  const view = render(subject(ready('alice')));
  typeSomething();

  view.rerender(subject({ status: 'syncing', message: null, owner: null }));
  view.rerender(subject(ready('alice')));

  expect(screen.getByRole('button')).toHaveTextContent('account:alice / nothing typed');
});

it('keeps the page when main republishes the owner it already had', () => {
  const view = render(subject(ready('alice')));
  typeSomething();

  // Every auth change republishes the runtime state; an unchanged owner is not a new one.
  view.rerender(subject(ready('alice')));

  expect(screen.getByRole('button')).toHaveTextContent('account:alice / secret note');
});
