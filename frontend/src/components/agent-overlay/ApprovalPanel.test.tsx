import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { t as translate } from '@/i18n/translate';
import type { MessageKey, UiLanguage } from '@/i18n/types';
import type { ActionApprovalBlocker } from '../../../electron/src/actions/actionLiveCore';
import { ApprovalPanel } from './ApprovalPanel';

function applyPatchBlocker(
  commandSummary: ActionApprovalBlocker['commandSummary']
): ActionApprovalBlocker {
  return {
    actionId: 'action-1',
    processId: 'process-1',
    approvalSessionId: 'approval-1',
    toolRequestId: 'request-1',
    toolId: 'apply_patch',
    intentClass: 'workspace_edit',
    commandSummary: { summary_kind: 'apply_patch', ...commandSummary },
  };
}

function bashBlocker(
  commandSummary: ActionApprovalBlocker['commandSummary']
): ActionApprovalBlocker {
  return {
    ...applyPatchBlocker({}),
    toolId: 'bash',
    intentClass: 'process_exec_local',
    commandSummary: { summary_kind: 'bash', ...commandSummary },
  };
}

const OUTSIDE_WORKSPACE_SUMMARY = {
  target_paths: ['/Users/me/Documents/Reports/q3.md'],
  outside_workspace: {
    folders: [{ path: '/Users/me/Documents/Reports', display_name: 'Reports' }],
    reason: null,
    can_allow_for_conversation: true,
  },
};

const TWO_FOLDER_COMMAND_SUMMARY = {
  command: 'touch made.txt',
  cwd: '/Users/me/Documents/Reports',
  timeout_ms: 60000,
  use_login_environment: false,
  outside_workspace: {
    folders: [
      { path: '/Users/me/Documents/Reports', display_name: 'Reports' },
      { path: '/Users/me/.cache/tool', display_name: 'tool' },
    ],
    reason: null,
    can_allow_for_conversation: true,
  },
};

const COMMAND_REASON = 'レポートの下書きを書き出すために、次のフォルダにファイルを作ります。';

function withReason(reason: string) {
  return {
    ...TWO_FOLDER_COMMAND_SUMMARY,
    outside_workspace: { ...TWO_FOLDER_COMMAND_SUMMARY.outside_workspace, reason },
  };
}

function renderPanel(language: UiLanguage, blocker: ActionApprovalBlocker) {
  const handlers = {
    onDecide: vi.fn(),
    onOpenWorkspaceSettings: vi.fn(),
  };
  return {
    ...handlers,
    ...render(
      <ApprovalPanel
        approvalPanel={blocker}
        isSubmittingApproval={false}
        {...handlers}
        t={(key: MessageKey, vars?: Record<string, string | number>) =>
          translate(language, key, vars)
        }
      />
    ),
  };
}

describe('ApprovalPanel', () => {
  afterEach(() => {
    cleanup();
  });

  it('asks in plain words about a folder outside the workspace and maps each choice', () => {
    const handlers = renderPanel('ja', applyPatchBlocker(OUTSIDE_WORKSPACE_SUMMARY));

    expect(
      screen.getByText('『Reports』フォルダのファイルを変更しようとしています。許可しますか？')
    ).toBeTruthy();
    expect(screen.getByText('/Users/me/Documents/Reports')).toBeTruthy();
    // The files being changed stay listed under the question.
    expect(screen.getByText('/Users/me/Documents/Reports/q3.md')).toBeTruthy();
    expect(
      screen.getByText(
        'このフォルダを作業フォルダに登録すると、次からはこの確認は出なくなります。',
        {
          exact: false,
        }
      )
    ).toBeTruthy();

    expect(screen.getAllByRole('button').map((button) => button.textContent)).toEqual([
      '許可しない',
      '今回だけ許可',
      'この会話では許可',
      '作業フォルダの設定を開く',
    ]);
    fireEvent.click(screen.getByRole('button', { name: '許可しない' }));
    fireEvent.click(screen.getByRole('button', { name: '今回だけ許可' }));
    fireEvent.click(screen.getByRole('button', { name: 'この会話では許可' }));
    expect(handlers.onDecide.mock.calls).toEqual([
      ['denied'],
      ['approved_once'],
      ['approved_for_conversation'],
    ]);
    fireEvent.click(screen.getByRole('button', { name: '作業フォルダの設定を開く' }));
    expect(handlers.onOpenWorkspaceSettings).toHaveBeenCalledTimes(1);
  });

  it('asks the same question in English', () => {
    renderPanel('en', applyPatchBlocker(OUTSIDE_WORKSPACE_SUMMARY));

    expect(
      screen.getByText('Pantaray wants to change files in the “Reports” folder. Allow it?')
    ).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Allow once' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Don’t allow' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Allow for this conversation' })).toBeTruthy();
    expect(
      screen.getByText(
        'Add this folder to your workspace folders and this check won’t appear next time.',
        { exact: false }
      )
    ).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Open workspace folder settings' })).toBeTruthy();
  });

  it('offers only a one-off approval for a folder that cannot be allowed for the conversation', () => {
    renderPanel(
      'ja',
      applyPatchBlocker({
        ...OUTSIDE_WORKSPACE_SUMMARY,
        outside_workspace: {
          ...OUTSIDE_WORKSPACE_SUMMARY.outside_workspace,
          can_allow_for_conversation: false,
        },
      })
    );

    expect(screen.getByRole('button', { name: '今回だけ許可' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'この会話では許可' })).toBeNull();
  });

  it('asks about the folder of a command run outside the workspace', () => {
    renderPanel(
      'ja',
      bashBlocker({
        ...TWO_FOLDER_COMMAND_SUMMARY,
        outside_workspace: {
          ...TWO_FOLDER_COMMAND_SUMMARY.outside_workspace,
          folders: TWO_FOLDER_COMMAND_SUMMARY.outside_workspace.folders.slice(0, 1),
        },
      })
    );

    expect(
      screen.getByText('『Reports』フォルダのファイルを変更しようとしています。許可しますか？')
    ).toBeTruthy();
    expect(screen.getByText('touch made.txt')).toBeTruthy();
    expect(screen.queryByRole('list')).toBeNull();
    expect(screen.getByRole('button', { name: 'この会話では許可' })).toBeTruthy();
  });

  it('lists every folder of an approval that opens several', () => {
    const { container } = renderPanel('ja', bashBlocker(TWO_FOLDER_COMMAND_SUMMARY));

    expect(screen.getByText('ローカルコマンドを実行します。')).toBeTruthy();
    expect(screen.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      '/Users/me/Documents/Reports',
      '/Users/me/.cache/tool',
    ]);
    expect(
      screen.getByText(
        'これらのフォルダを作業フォルダに登録すると、次からはこの確認は出なくなります。',
        { exact: false }
      )
    ).toBeTruthy();
    expect(screen.getAllByRole('button').map((button) => button.textContent)).toEqual([
      '許可しない',
      '今回だけ許可',
      'この会話では許可',
      '作業フォルダの設定を開く',
    ]);
    // Without a reason the command stays in view, as before.
    expect(screen.getByText('touch made.txt').closest('details')).toBeNull();
    expect(container.querySelector('details')).toBeNull();
    expect(screen.queryByText('変更するフォルダ')).toBeNull();
  });

  it('leads with the reason and keeps the command behind a closed disclosure', () => {
    const handlers = renderPanel('ja', bashBlocker(withReason(COMMAND_REASON)));

    const headline = screen.getByText(COMMAND_REASON);
    expect(headline.previousElementSibling?.textContent).toBe('承認が必要です');
    expect(screen.queryByText('ローカルコマンドを実行します。')).toBeNull();
    expect(screen.getByText('変更するフォルダ')).toBeTruthy();
    expect(screen.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      '/Users/me/Documents/Reports',
      '/Users/me/.cache/tool',
    ]);

    const disclosure = screen.getByText('touch made.txt').closest('details');
    expect(disclosure).not.toBeNull();
    expect(disclosure?.open).toBe(false);
    expect(
      screen.getByText('/Users/me/Documents/Reports', { selector: 'dd' }).closest('details')
    ).toBe(disclosure);
    const summary = screen.getByText('詳細');
    expect(summary.tagName).toBe('SUMMARY');
    fireEvent.click(summary);
    expect(disclosure?.open).toBe(true);

    expect(
      screen.getByText(
        'これらのフォルダを作業フォルダに登録すると、次からはこの確認は出なくなります。',
        { exact: false }
      )
    ).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '許可しない' }));
    fireEvent.click(screen.getByRole('button', { name: '今回だけ許可' }));
    fireEvent.click(screen.getByRole('button', { name: 'この会話では許可' }));
    expect(handlers.onDecide.mock.calls).toEqual([
      ['denied'],
      ['approved_once'],
      ['approved_for_conversation'],
    ]);
  });

  it('leads with the reason in English too', () => {
    const reason = 'To save the report draft, it will create files in these folders.';
    renderPanel('en', bashBlocker(withReason(reason)));

    expect(screen.getByText(reason)).toBeTruthy();
    expect(screen.queryByText('Run a local command.')).toBeNull();
    expect(screen.getByText('Folders it will change')).toBeTruthy();
    expect(screen.getByText('Details').tagName).toBe('SUMMARY');
    expect(screen.getByText('touch made.txt').closest('details')?.open).toBe(false);
    expect(screen.getByRole('button', { name: 'Allow once' })).toBeTruthy();
  });

  it('shows an HTML-looking reason as text', () => {
    const reason = '<img src="x" onerror="alert(1)"><b>bold</b>';
    const { container } = renderPanel('ja', bashBlocker(withReason(reason)));

    expect(screen.getByText(reason)).toBeTruthy();
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('b')).toBeNull();
  });

  it('names several folders in English too', () => {
    renderPanel('en', bashBlocker(TWO_FOLDER_COMMAND_SUMMARY));

    expect(
      screen.getByText(
        'Add these folders to your workspace folders and this check won’t appear next time.',
        { exact: false }
      )
    ).toBeTruthy();
  });

  it('keeps the existing wording for an approval inside the workspace', () => {
    renderPanel('ja', applyPatchBlocker({ target_paths: ['/repo/a.txt'] }));

    expect(screen.getByText('ファイルを変更します。')).toBeTruthy();
    expect(screen.getAllByRole('button').map((button) => button.textContent)).toEqual([
      '拒否',
      '許可',
    ]);
  });
});
