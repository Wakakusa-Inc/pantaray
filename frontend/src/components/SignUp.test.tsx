import React from 'react';
import { AuthError } from '@supabase/supabase-js';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

const { navigateMock, signUpMock } = vi.hoisted(() => ({
  navigateMock: vi.fn(),
  signUpMock: vi.fn(),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock('../hooks/useAuth', () => {
  return {
    useAuth: () => ({
      signUp: signUpMock,
    }),
  };
});

vi.mock('@/components/BrandWordmark', () => {
  return { BrandWordmark: () => React.createElement('div', { 'data-testid': 'brand' }) };
});

vi.mock('@/context/useI18n', () => {
  return {
    useI18n: () => ({
      t: (key: string) => key,
    }),
  };
});

import SignUp from './SignUp';

describe('SignUp', () => {
  beforeEach(() => {
    navigateMock.mockClear();
    signUpMock.mockReset();
    signUpMock.mockResolvedValue({ status: 'created', error: null });
  });

  afterEach(() => {
    vi.useRealTimers();
    cleanup();
  });

  it('shows an existing-account error instead of continuing to email verification', async () => {
    signUpMock.mockResolvedValue({
      status: 'already_registered',
      error: new AuthError('Account already exists.'),
    });

    render(
      <MemoryRouter initialEntries={['/signup']}>
        <SignUp />
      </MemoryRouter>
    );

    fireEvent.change(screen.getByPlaceholderText('auth.form.emailPlaceholder'), {
      target: { value: 'used@example.com' },
    });
    fireEvent.change(screen.getByPlaceholderText('auth.form.passwordPlaceholder'), {
      target: { value: 'Password1!' },
    });
    fireEvent.change(screen.getByPlaceholderText('auth.form.passwordConfirmPlaceholder'), {
      target: { value: 'Password1!' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'auth.form.signupButton' }));

    await screen.findByText('auth.error.signupAlreadyRegistered');

    expect(signUpMock).toHaveBeenCalledWith('used@example.com', 'Password1!');
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it('continues to email verification after a new account is created', async () => {
    vi.useFakeTimers();

    render(
      <MemoryRouter initialEntries={['/signup']}>
        <SignUp />
      </MemoryRouter>
    );

    fireEvent.change(screen.getByPlaceholderText('auth.form.emailPlaceholder'), {
      target: { value: 'new@example.com' },
    });
    fireEvent.change(screen.getByPlaceholderText('auth.form.passwordPlaceholder'), {
      target: { value: 'Password1!' },
    });
    fireEvent.change(screen.getByPlaceholderText('auth.form.passwordConfirmPlaceholder'), {
      target: { value: 'Password1!' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'auth.form.signupButton' }));

    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      vi.advanceTimersByTime(500);
    });

    expect(signUpMock).toHaveBeenCalledWith('new@example.com', 'Password1!');
    expect(navigateMock).toHaveBeenCalledWith('/email-verification');
  });
});
