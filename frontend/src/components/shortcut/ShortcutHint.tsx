import type { MessageKey } from '@/i18n/types';

import { acceleratorKeycaps, keycapsLabel } from './acceleratorKeycaps';
import type { ShortcutHintState } from './useGlobalShortcutHint';
import './shortcutHint.css';

type Translate = (key: MessageKey, vars?: Record<string, string | number>) => string;

/** Keycaps for an accelerator that is known to be registered. */
export function ShortcutKeycaps({ accelerator, t }: { accelerator: string; t: Translate }) {
  const keycaps = acceleratorKeycaps(accelerator, window.electron?.process.platform === 'darwin');
  return (
    <span
      className="shortcut-keycaps"
      role="img"
      aria-label={t('shortcut.hint.label', { keys: keycapsLabel(keycaps) })}
    >
      {keycaps.map((keycap, index) => (
        <kbd key={`${index}:${keycap.label}`} className="shortcut-keycap">
          {keycap.symbol}
        </kbd>
      ))}
    </span>
  );
}

/** Shows the global shortcut that opens the same Overlay as the adjacent button. */
export function ShortcutHint({ state, t }: { state: ShortcutHintState; t: Translate }) {
  if (state.status === 'ready') return <ShortcutKeycaps accelerator={state.accelerator} t={t} />;
  return (
    <span className="shortcut-hint-status">
      {t(state.status === 'loading' ? 'shortcut.hint.loading' : 'shortcut.hint.unavailable')}
    </span>
  );
}
