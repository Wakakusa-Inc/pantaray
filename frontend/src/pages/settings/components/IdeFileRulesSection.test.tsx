import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { IdeFileRulesSection } from './IdeFileRulesSection';
import { DEFAULT_IDE_SENSITIVE_PRESETS } from '../model';
import type { Translate } from '../types';

// The identity translator keeps assertions on message keys, not on copy.
const translate = ((key: string) => key) as Translate;

describe('IdeFileRulesSection', () => {
  it('reports a load failure instead of staying on the loading message', () => {
    render(
      <IdeFileRulesSection
        ideFileRules={null}
        ideFileRulesError="settings.ideFileRules.loadFailed"
        ideSensitivePresets={DEFAULT_IDE_SENSITIVE_PRESETS}
        isLoadingIdeFileRules={false}
        setIdeSensitivePresetEnv={vi.fn()}
        t={translate}
      />
    );

    expect(screen.getByText('settings.ideFileRules.loadFailed')).toBeTruthy();
    expect(screen.queryByText('settings.ideFileRules.loadingRules')).toBeNull();
  });
});
