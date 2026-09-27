import { describe, expect, it } from 'vitest';

import { acceleratorKeycaps, keycapsLabel } from './acceleratorKeycaps';

const symbols = (accelerator: string, isMac: boolean) =>
  acceleratorKeycaps(accelerator, isMac).map((keycap) => keycap.symbol);

describe('acceleratorKeycaps', () => {
  it('renders macOS glyphs in ⌃⌥⇧⌘ order regardless of the accelerator order', () => {
    expect(symbols('Option+Space', true)).toEqual(['⌥', 'Space']);
    expect(symbols('Command+Shift+K', true)).toEqual(['⇧', '⌘', 'K']);
    expect(symbols('Control+Alt+Command+Space', true)).toEqual(['⌃', '⌥', '⌘', 'Space']);
    expect(symbols('CommandOrControl+Shift+K', true)).toEqual(['⇧', '⌘', 'K']);
  });

  it('spells modifiers out on other platforms', () => {
    expect(symbols('Option+Space', false)).toEqual(['Alt', 'Space']);
    expect(symbols('CommandOrControl+Shift+K', false)).toEqual(['Shift', 'Ctrl', 'K']);
    expect(symbols('Super+F5', false)).toEqual(['Super', 'F5']);
  });

  it('keeps a key without modifiers and shows unknown tokens verbatim', () => {
    expect(symbols('F7', true)).toEqual(['F7']);
    expect(symbols('Hyper+F7', true)).toEqual(['Hyper', 'F7']);
  });

  it('speaks modifier names instead of glyphs', () => {
    expect(keycapsLabel(acceleratorKeycaps('Option+Space', true))).toBe('Option Space');
    expect(keycapsLabel(acceleratorKeycaps('Control+Shift+Command+L', true))).toBe(
      'Control Shift Command L'
    );
  });
});
