import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApprovalModeMenu } from './ApprovalModeMenu';
import { useActionApprovalMode } from './useActionApprovalMode';
import { UiLanguageProvider } from '@/context/UiLanguageContext';

const getActionApprovalMode = vi.fn();
const setActionApprovalMode = vi.fn();
const getWorkspaceEditCommandPreference = vi.fn();
const setWorkspaceEditCommandPreference = vi.fn();

function MenuHarness({ actionId }: { actionId: string | null }) {
  return <ApprovalModeMenu approvalMode={useActionApprovalMode(actionId, null)} />;
}

function renderMenu(actionId: string | null) {
  return render(
    <UiLanguageProvider initialLanguage="en">
      <MenuHarness actionId={actionId} />
    </UiLanguageProvider>
  );
}

describe('ApprovalModeMenu', () => {
  beforeEach(() => {
    getActionApprovalMode.mockReset();
    setActionApprovalMode.mockReset();
    getWorkspaceEditCommandPreference.mockReset();
    setWorkspaceEditCommandPreference.mockReset();
    Object.defineProperty(window, 'electron', {
      configurable: true,
      value: {
        agentOverlay: { getActionApprovalMode, setActionApprovalMode },
        approval: { getWorkspaceEditCommandPreference, setWorkspaceEditCommandPreference },
      },
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('states the mode in force and opens the menu on it', async () => {
    getActionApprovalMode.mockResolvedValue({
      action_id: 'act-1',
      approval_mode: 'always_allow',
      source: 'user_default',
    });

    renderMenu('act-1');

    const trigger = await screen.findByRole('button', {
      name: 'File edit and command permissions: Auto-approve',
    });
    expect(trigger).toBeEnabled();
    expect(trigger).toHaveAttribute('title', 'Change permissions');
    expect(getActionApprovalMode).toHaveBeenCalledWith('act-1');
  });

  it('writes the picked mode for this conversation only', async () => {
    getActionApprovalMode.mockResolvedValue({
      action_id: 'act-1',
      approval_mode: 'prompt_each_time',
      source: 'user_default',
    });
    setActionApprovalMode.mockResolvedValue({
      action_id: 'act-1',
      approval_mode: 'always_allow',
      source: 'action',
    });

    renderMenu('act-1');
    fireEvent.click(await screen.findByRole('button', { name: /permissions: Ask every time/ }));
    fireEvent.click(screen.getByRole('menuitemradio', { name: /Auto-approve/ }));

    await waitFor(() =>
      expect(setActionApprovalMode).toHaveBeenCalledWith({
        actionId: 'act-1',
        approvalMode: 'always_allow',
      })
    );
    expect(
      await screen.findByRole('button', { name: /permissions: Auto-approve/ })
    ).toBeInTheDocument();
  });

  it('exposes radio menu semantics and returns focus when Escape closes it', async () => {
    getActionApprovalMode.mockResolvedValue({
      action_id: 'act-1',
      approval_mode: 'prompt_each_time',
      source: 'action',
    });

    renderMenu('act-1');
    const trigger = await screen.findByRole('button', { name: /permissions: Ask every time/ });
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(trigger);

    const menu = screen.getByRole('menu', { name: 'File edit and command permissions' });
    const items = screen.getAllByRole('menuitemradio');
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(items.map((item) => item.getAttribute('aria-checked'))).toEqual(['true', 'false']);
    await waitFor(() => expect(items[0]).toHaveFocus());

    fireEvent.keyDown(menu, { key: 'ArrowDown' });
    expect(items[1]).toHaveFocus();

    fireEvent.keyDown(menu, { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it('floats above the trigger, clamped inside the overlay window, and follows it on resize', async () => {
    getActionApprovalMode.mockResolvedValue({
      action_id: 'act-1',
      approval_mode: 'prompt_each_time',
      source: 'action',
    });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 560 });
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 420 });
    vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(120);
    vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(260);

    const { container } = renderMenu('act-1');
    const trigger = await screen.findByRole('button', { name: /permissions: Ask every time/ });
    const anchor = { top: 470, bottom: 498, left: 300, height: 28, width: 176 };
    vi.spyOn(trigger, 'getBoundingClientRect').mockImplementation(
      () => anchor as unknown as DOMRect
    );

    fireEvent.click(trigger);
    const menu = screen.getByRole('menu');
    // Portalled out of the composer so the overlay's measured content keeps its height.
    expect(container.contains(menu)).toBe(false);
    expect(menu.parentElement).toBe(document.body);
    // No room below the trigger (560 - 498 < 120), so it opens upward…
    expect(menu.style.top).toBe('344px');
    // …and the left edge is clamped to keep the 260px popover inside the window.
    expect(menu.style.left).toBe('152px');

    Object.assign(anchor, { top: 120, bottom: 148, left: 24 });
    fireEvent(window, new Event('resize'));
    expect(menu.style.top).toBe('154px');
    expect(menu.style.left).toBe('24px');
  });

  it('lets a new conversation pick draft consent without changing Settings', async () => {
    getWorkspaceEditCommandPreference.mockResolvedValue({
      scope_type: 'global',
      scope_ref: null,
      approval_mode: 'always_allow',
      applies_to: ['workspace_edit_and_command'],
    });

    renderMenu(null);

    const trigger = await screen.findByRole('button', {
      name: 'File edit and command permissions: Auto-approve',
    });
    expect(trigger).toBeEnabled();
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole('menuitemradio', { name: /Ask every time/ }));
    expect(screen.getByRole('button', { name: /permissions: Ask every time/ })).toBeEnabled();
    expect(getActionApprovalMode).not.toHaveBeenCalled();
    expect(setActionApprovalMode).not.toHaveBeenCalled();
    expect(setWorkspaceEditCommandPreference).not.toHaveBeenCalled();
  });

  it('closes the old conversation menu while a new draft loads its default', async () => {
    getActionApprovalMode.mockResolvedValue({ approval_mode: 'always_allow' });
    getWorkspaceEditCommandPreference.mockResolvedValue({ approval_mode: 'prompt_each_time' });
    const { rerender } = renderMenu('act-1');
    fireEvent.click(await screen.findByRole('button', { name: /permissions: Auto-approve/ }));
    expect(screen.getByRole('menu')).toBeInTheDocument();
    rerender(
      <UiLanguageProvider initialLanguage="en">
        <MenuHarness actionId={null} />
      </UiLanguageProvider>
    );
    await screen.findByRole('button', { name: /permissions: Ask every time/ });
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('ignores an old account default response after resetting a draft', async () => {
    let resolveOld!: (value: { approval_mode: 'always_allow' }) => void;
    getWorkspaceEditCommandPreference
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveOld = resolve;
        })
      )
      .mockResolvedValueOnce({ approval_mode: 'prompt_each_time' });
    const { result } = renderHook(() => useActionApprovalMode(null, null));
    act(() => result.current.reset());
    await waitFor(() => expect(result.current.mode).toBe('prompt_each_time'));
    await act(async () => resolveOld({ approval_mode: 'always_allow' }));
    expect(result.current.mode).toBe('prompt_each_time');
  });

  it('does not let a previous Action save replace a new draft choice', async () => {
    getActionApprovalMode.mockResolvedValue({ approval_mode: 'prompt_each_time' });
    getWorkspaceEditCommandPreference.mockResolvedValue({ approval_mode: 'prompt_each_time' });
    let resolveWrite!: (value: { approval_mode: 'always_allow' }) => void;
    setActionApprovalMode.mockReturnValue(
      new Promise((resolve) => {
        resolveWrite = resolve;
      })
    );
    const { result, rerender } = renderHook(
      ({ actionId }: { actionId: string | null }) => useActionApprovalMode(actionId, null),
      { initialProps: { actionId: 'act-1' as string | null } }
    );
    await waitFor(() => expect(result.current.mode).toBe('prompt_each_time'));
    act(() => {
      void result.current.selectMode('always_allow');
    });
    expect(result.current.isSaving).toBe(true);
    expect(result.current.mode).toBe('prompt_each_time');
    rerender({ actionId: null });
    await waitFor(() => expect(result.current.mode).toBe('prompt_each_time'));
    await act(async () => result.current.selectMode('prompt_each_time'));
    await act(async () => resolveWrite({ approval_mode: 'always_allow' }));
    expect(result.current.mode).toBe('prompt_each_time');
    expect(result.current.isSaving).toBe(false);
  });
  it('re-reads effective consent after a save response fails', async () => {
    getActionApprovalMode.mockResolvedValueOnce({ approval_mode: 'prompt_each_time' });
    setActionApprovalMode.mockRejectedValue(new Error('response lost'));
    renderMenu('act-1');
    fireEvent.click(await screen.findByRole('button', { name: /permissions: Ask every time/ }));
    fireEvent.click(screen.getByRole('menuitemradio', { name: /Auto-approve/ }));
    const retry = await screen.findByRole('button', { name: 'Retry loading permissions' });
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to change the permission mode.');
    getActionApprovalMode.mockResolvedValueOnce({ approval_mode: 'always_allow' });
    fireEvent.click(retry);
    expect(await screen.findByRole('button', { name: /permissions: Auto-approve/ })).toBeEnabled();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
