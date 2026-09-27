import { z } from 'zod';

import { MAX_ACCELERATOR_LENGTH } from './limits';

const FUNCTION_KEY_PATTERN = /^F(?:[1-9]|1\d|2[0-4])$/;
const MODIFIER_PATTERN = /^(?:Command|Super|Control|Option|Alt|Shift)$/;
const KEY_TOKEN_PATTERN =
  /^(?:[A-Z0-9]|F(?:[1-9]|1\d|2[0-4])|Space|Up|Down|Left|Right|Backspace|Delete|End|Enter|Esc|Home|Insert|PageDown|PageUp|Tab|num(?:[0-9]|add|dec|div|mult|sub)|Plus|[\x21-\x2A\x2C-\x2F\x3A-\x40\x5B-\x60\x7B-\x7E])$/;

function isAllowedAccelerator(accelerator: string): boolean {
  const tokens = accelerator.split('+');
  const key = tokens.pop();
  if (!key || key === 'F12' || !KEY_TOKEN_PATTERN.test(key)) return false;
  if (!tokens.every((token) => MODIFIER_PATTERN.test(token))) return false;
  if (new Set(tokens).size !== tokens.length) return false;
  return FUNCTION_KEY_PATTERN.test(key) || tokens.some((token) => token !== 'Shift');
}

export type GlobalShortcutFailure =
  | 'settings_unreadable'
  | 'registration_unavailable'
  | 'persistence_failed';

export type GlobalShortcutState = Readonly<{
  accelerator: string | null;
  failure: GlobalShortcutFailure | null;
}>;

export type GlobalShortcutChangeResult =
  | Readonly<{ ok: true; state: GlobalShortcutState }>
  | Readonly<{
      ok: false;
      reason: 'registration_unavailable' | 'persistence_failed';
      state: GlobalShortcutState;
    }>;

export const GlobalShortcutAcceleratorSchema = z
  .string()
  .trim()
  .max(MAX_ACCELERATOR_LENGTH)
  .refine(isAllowedAccelerator, 'Global shortcut accelerator is not allowed.');
