import { useEffect, useState } from 'react';

export type ShortcutHintState =
  | { status: 'loading' }
  | { status: 'unavailable' }
  | { status: 'ready'; accelerator: string };

/**
 * Reads the configured global shortcut once per mount. The settings page lives on a sibling
 * route, so returning to a page after a change remounts it with the new accelerator.
 */
export function useGlobalShortcutHint(): ShortcutHintState {
  const [state, setState] = useState<ShortcutHintState>({ status: 'loading' });
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const shortcutApi = window.electron?.shortcut;
        if (!shortcutApi) throw new Error('Shortcut settings bridge is unavailable.');
        const { accelerator, failure } = await shortcutApi.getState();
        if (cancelled) return;
        // A failure means the accelerator is configured but not registered: pressing it does nothing.
        setState(
          accelerator && !failure ? { status: 'ready', accelerator } : { status: 'unavailable' }
        );
      } catch {
        if (!cancelled) setState({ status: 'unavailable' });
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);
  return state;
}
