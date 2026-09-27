import { z } from 'zod';

import type { createLocalBackendClient } from '../localBackend/client';
import { CanonicalIdentitySchema } from './actionContracts';

export type ActionApprovalMode = 'prompt_each_time' | 'always_allow';

const ActionApprovalModeResponseSchema = z
  .object({
    action_id: CanonicalIdentitySchema,
    approval_mode: z.enum(['prompt_each_time', 'always_allow']),
    source: z.enum(['action', 'user_default']),
  })
  .strict();
export type ActionApprovalModeResponse = z.infer<typeof ActionApprovalModeResponseSchema>;

export class ActionApprovalModeResponseError extends Error {
  constructor() {
    super('Invalid Action approval mode response.');
    this.name = 'ActionApprovalModeResponseError';
  }
}

export function createActionApprovalModeFetcher(params: {
  requestJson: ReturnType<typeof createLocalBackendClient>['requestJson'];
  getUserId: () => string | null;
}): {
  get: (actionId: string) => Promise<ActionApprovalModeResponse>;
  update: (actionId: string, mode: ActionApprovalMode) => Promise<ActionApprovalModeResponse>;
} {
  const buildPath = (actionId: string): string => {
    const userId = params.getUserId();
    if (!userId) throw new Error('Missing authenticated user id.');
    return `/v1/agents/users/${encodeURIComponent(userId)}/actions/${encodeURIComponent(
      actionId
    )}/approval-mode`;
  };
  const parse = (payload: unknown, actionId: string): ActionApprovalModeResponse => {
    const result = ActionApprovalModeResponseSchema.safeParse(payload);
    if (!result.success || result.data.action_id !== actionId) {
      throw new ActionApprovalModeResponseError();
    }
    return result.data;
  };

  return {
    get: async (actionId) =>
      parse(
        await params.requestJson<unknown>({ path: buildPath(actionId), method: 'GET' }),
        actionId
      ),
    update: async (actionId, mode) =>
      parse(
        await params.requestJson<unknown>({
          path: buildPath(actionId),
          method: 'PUT',
          body: { approval_mode: mode },
        }),
        actionId
      ),
  };
}
