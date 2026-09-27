import { describe, expect, it } from 'vitest';

import { getConversationHistoryStatusMeta } from './statusTokens';

describe('getConversationHistoryStatusMeta', () => {
  it.each([
    ['running', 'history.status.running', 'info'],
    ['approval_pending', 'history.status.approvalPending', 'warning'],
  ] as const)('%s を履歴用の表示 token に変換する', (status, labelKey, tone) => {
    expect(getConversationHistoryStatusMeta(status)).toEqual({ labelKey, tone });
  });

  it('idle は終了・失敗・中断を区別できないためバッジを持たない', () => {
    expect(getConversationHistoryStatusMeta('idle')).toBeNull();
  });
});
