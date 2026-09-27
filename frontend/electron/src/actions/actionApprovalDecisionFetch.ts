import { z } from 'zod';

import type { createLocalBackendClient } from '../localBackend/client';
import { CanonicalIdentitySchema } from './actionContracts';

export const OVERLAY_APPROVAL_DECISIONS = [
  'approved_once',
  'approved_for_conversation',
  'denied',
] as const;
export type OverlayApprovalDecision = (typeof OVERLAY_APPROVAL_DECISIONS)[number];

export type SubmitApprovalDecisionPayload = {
  actionId: string;
  processId: string;
  approvalSessionId: string;
  toolRequestId: string;
  decision: OverlayApprovalDecision;
};

const ActionApprovalDecisionResponseSchema = z
  .object({
    process_id: CanonicalIdentitySchema,
    approval_session_id: CanonicalIdentitySchema,
    decision: z.enum(OVERLAY_APPROVAL_DECISIONS),
    accepted: z.literal(true),
  })
  .strict();
export type ActionApprovalDecisionResponse = z.infer<typeof ActionApprovalDecisionResponseSchema>;

export class ActionApprovalDecisionResponseError extends Error {
  constructor() {
    super('Invalid Action approval decision response.');
    this.name = 'ActionApprovalDecisionResponseError';
  }
}

export function createActionApprovalDecisionFetcher(params: {
  requestJson: ReturnType<typeof createLocalBackendClient>['requestJson'];
  getUserId: () => string | null;
}): (payload: SubmitApprovalDecisionPayload) => Promise<ActionApprovalDecisionResponse> {
  return async function submitApprovalDecision(
    payload: SubmitApprovalDecisionPayload
  ): Promise<ActionApprovalDecisionResponse> {
    const userId = params.getUserId();
    if (!userId) throw new Error('Missing authenticated user id.');
    const response = await params.requestJson<unknown>({
      path: `/v1/agents/users/${encodeURIComponent(userId)}/actions/${encodeURIComponent(
        payload.actionId
      )}/approvals`,
      method: 'POST',
      body: {
        process_id: payload.processId,
        approval_session_id: payload.approvalSessionId,
        tool_request_id: payload.toolRequestId,
        decision: payload.decision,
      },
    });
    const result = ActionApprovalDecisionResponseSchema.safeParse(response);
    if (
      !result.success ||
      result.data.process_id !== payload.processId ||
      result.data.approval_session_id !== payload.approvalSessionId ||
      result.data.decision !== payload.decision
    ) {
      throw new ActionApprovalDecisionResponseError();
    }
    return result.data;
  };
}
