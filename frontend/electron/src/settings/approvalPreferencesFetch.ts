import type { createLocalBackendClient } from '../localBackend/client';

export type ApprovalMode = 'prompt_each_time' | 'always_allow';

export type ApprovalPreferenceResponse = {
  scope_type: 'global';
  scope_ref: null;
  approval_mode: ApprovalMode;
  applies_to: ['workspace_edit_and_command'];
};
function isApprovalPreferenceResponse(value: unknown): value is ApprovalPreferenceResponse {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Partial<ApprovalPreferenceResponse>;
  return (
    candidate.scope_type === 'global' &&
    candidate.scope_ref === null &&
    (candidate.approval_mode === 'prompt_each_time' ||
      candidate.approval_mode === 'always_allow') &&
    Array.isArray(candidate.applies_to) &&
    candidate.applies_to.length === 1 &&
    candidate.applies_to[0] === 'workspace_edit_and_command'
  );
}

function parseApprovalPreferenceResponse(payload: unknown): ApprovalPreferenceResponse {
  if (!isApprovalPreferenceResponse(payload)) {
    throw new Error('Approval preference response is invalid.');
  }
  return payload;
}

function buildApprovalPreferenceUrl(userId: string): string {
  return `/v1/agents/users/${encodeURIComponent(
    userId
  )}/approval-preferences/workspace-edit-and-command`;
}

export function createApprovalPreferenceFetcher(params: {
  requestJson: ReturnType<typeof createLocalBackendClient>['requestJson'];
  getUserId: () => string | null;
}): {
  get: () => Promise<ApprovalPreferenceResponse>;
  update: (approvalMode: ApprovalMode) => Promise<ApprovalPreferenceResponse>;
} {
  const buildUrl = (): string => {
    const userId = params.getUserId();
    if (!userId) {
      throw new Error('Missing authenticated user id.');
    }
    return buildApprovalPreferenceUrl(userId);
  };

  return {
    get: async (): Promise<ApprovalPreferenceResponse> => {
      return await parseApprovalPreferenceResponse(
        await params.requestJson<unknown>({
          path: buildUrl(),
          method: 'GET',
        })
      );
    },
    update: async (approvalMode: ApprovalMode): Promise<ApprovalPreferenceResponse> => {
      return await parseApprovalPreferenceResponse(
        await params.requestJson<unknown>({
          path: buildUrl(),
          method: 'PUT',
          body: { approval_mode: approvalMode },
        })
      );
    },
  };
}
