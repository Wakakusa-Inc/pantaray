import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { UiLanguageContext } from '@/context/uiLanguageContextShared';
import { t as translate } from '@/i18n/translate';
import type { UiLanguage } from '@/i18n/types';

vi.mock('@/components/BrandWordmark', () => {
  return { BrandWordmark: () => React.createElement('div', { 'data-testid': 'brand' }) };
});

import ConfirmationSuccess from './ConfirmationSuccess';
import EmailVerificationPage from './EmailVerificationPage';
import PasswordResetSuccess from './PasswordResetSuccess';

function renderWithLanguage(ui: React.ReactNode, language: UiLanguage = 'en') {
  return render(
    <UiLanguageContext.Provider
      value={{
        language,
        setLanguage: vi.fn(async () => undefined),
        t: (key, vars) => translate(language, key, vars),
        formatDateTime: (date) => date.toISOString(),
      }}
    >
      <MemoryRouter>{ui}</MemoryRouter>
    </UiLanguageContext.Provider>
  );
}

describe('PasswordResetSuccess', () => {
  afterEach(() => {
    cleanup();
  });

  it('renders password reset success copy from the English catalog', () => {
    renderWithLanguage(<PasswordResetSuccess />, 'en');

    expect(screen.getByRole('heading', { name: 'Password reset complete' })).toBeInTheDocument();
    const loginLink = screen.getByRole('link', { name: 'Return to login' });

    expect(loginLink).toHaveAttribute('href', '/login');
  });

  it('renders password reset success copy from the Japanese catalog', () => {
    renderWithLanguage(<PasswordResetSuccess />, 'ja');

    expect(
      screen.getByRole('heading', { name: 'パスワード再設定が完了しました' })
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'ログインへ戻る' })).toHaveAttribute('href', '/login');
  });

  it('renders email verification copy from the catalog', () => {
    renderWithLanguage(<EmailVerificationPage />, 'ja');

    expect(screen.getByRole('heading', { name: 'メールアドレスの確認' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'ログインへ戻る' })).toHaveAttribute('href', '/login');
  });

  it('renders confirmation success copy from the catalog', () => {
    renderWithLanguage(<ConfirmationSuccess />, 'ja');

    expect(
      screen.getByRole('heading', { name: 'アカウント作成が完了しました' })
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'ログインへ進む' })).toHaveAttribute('href', '/login');
  });
});
