import ReactDOM from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import type { ActionLiveUpdate } from '../electron/src/actions/actionLiveCore';
import {
  readConversationScrollPosition,
  saveConversationScrollPosition,
} from './components/agent-overlay/conversationScrollPosition';

vi.mock('./App', () => ({ default: () => null }));
vi.mock('./context/AuthContext', () => ({ AuthProvider: () => null }));

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
  delete window.electron;
  document.body.replaceChildren();
});

it('clears shared reading positions on auth reset without any Overlay mounted', async () => {
  const listeners: ((update: ActionLiveUpdate) => void)[] = [];
  Object.defineProperty(window, 'electron', {
    configurable: true,
    value: {
      actions: {
        onConversationUpdated: (callback: (update: ActionLiveUpdate) => void) => {
          listeners.push(callback);
          return () => {};
        },
      },
    },
  });
  vi.spyOn(ReactDOM, 'createRoot').mockReturnValue({ render: vi.fn(), unmount: vi.fn() });
  document.body.innerHTML = '<div id="root"></div>';
  saveConversationScrollPosition('old-account-action', { top: 300, atBottom: false, pageCount: 5 });
  localStorage.setItem('pantaray_ui_language', 'ja');

  await import('./main');
  for (const listener of listeners) listener({ kind: 'reset' });

  expect(readConversationScrollPosition('old-account-action')).toBeNull();
  expect(localStorage.getItem('pantaray_ui_language')).toBe('ja');
});
