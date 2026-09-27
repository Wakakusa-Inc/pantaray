import { useCallback, useEffect, useRef, useState } from 'react';

import type { MessageKey } from '@/i18n/types';
import type { ActionApprovalBlocker } from '../../../electron/src/actions/actionLiveCore';
import type { ApprovalDecision } from './approvalDisplayModel';

export function useActionApprovalDecisionController({
  t,
}: {
  t: (key: MessageKey, vars?: Record<string, string | number>) => string;
}) {
  const [approvalBlockers, setApprovalBlockers] = useState<readonly ActionApprovalBlocker[]>([]);
  const [isSubmittingApproval, setIsSubmittingApproval] = useState(false);
  const [approvalErrorMessage, setApprovalErrorMessage] = useState<string | null>(null);
  const approvalKey = JSON.stringify(
    approvalBlockers.map((blocker) => [
      blocker.processId,
      blocker.approvalSessionId,
      blocker.toolRequestId,
    ])
  );
  const currentApprovalKey = useRef(approvalKey);
  currentApprovalKey.current = approvalKey;

  useEffect(() => {
    setApprovalErrorMessage(null);
    setIsSubmittingApproval(false);
  }, [approvalKey]);

  const submitApprovalDecision = useCallback(
    async (decision: ApprovalDecision, blocker: ActionApprovalBlocker) => {
      const requestKey = approvalKey;
      setIsSubmittingApproval(true);
      setApprovalErrorMessage(null);
      try {
        const submit = window.electron?.agentOverlay?.submitApprovalDecision;
        if (!submit) throw new Error('Approval bridge is unavailable.');
        await submit({
          actionId: blocker.actionId,
          processId: blocker.processId,
          approvalSessionId: blocker.approvalSessionId,
          toolRequestId: blocker.toolRequestId,
          decision,
        });
      } catch {
        if (currentApprovalKey.current === requestKey) {
          setApprovalErrorMessage(t('overlay.approvalRequired.submitFailed'));
        }
      } finally {
        if (currentApprovalKey.current === requestKey) setIsSubmittingApproval(false);
      }
    },
    [approvalKey, t]
  );

  return {
    approvalBlockers,
    approvalErrorMessage,
    approvalUiState:
      approvalBlockers.length > 0 ? ('approval_pending' as const) : ('hidden' as const),
    isSubmittingApproval,
    setApprovalBlockers,
    submitApprovalDecision,
  };
}
