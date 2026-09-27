/**
 * Zod schemas for the overlay approval IPC payloads.
 *
 * Shapes mirror `SubmitApprovalDecisionPayload` in
 * `actions/actionApprovalDecisionFetch.ts` and the Action approval mode
 * contract in `actions/actionApprovalModeFetch.ts`.
 */

import { z } from 'zod';

import { OVERLAY_APPROVAL_DECISIONS } from '../../actions/actionApprovalDecisionFetch';
import { IdSchema } from './workspaceSettings';

export const SubmitApprovalDecisionPayloadSchema = z
  .object({
    actionId: IdSchema,
    processId: IdSchema,
    approvalSessionId: IdSchema,
    toolRequestId: IdSchema,
    decision: z.enum(OVERLAY_APPROVAL_DECISIONS),
  })
  .strict();

export const ActionApprovalModeUpdateSchema = z
  .object({
    actionId: IdSchema,
    approvalMode: z.enum(['prompt_each_time', 'always_allow']),
  })
  .strict();
