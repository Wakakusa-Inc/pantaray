import type {
  ActionApprovalDecisionResponse,
  SubmitApprovalDecisionPayload,
} from './actionApprovalDecisionFetch';
import { LocalBackendRequestError } from '../localBackend/client';
import type { ResumeProcessRequest } from '../orchestration/contracts';

type Dependencies = {
  submitDecision: (
    payload: SubmitApprovalDecisionPayload
  ) => Promise<ActionApprovalDecisionResponse>;
  enqueueResumeRequest: (request: ResumeProcessRequest) => void;
  isResultCurrent: () => boolean;
  // Settles the decision locally and answers with the Action's root relay process id.
  onDecisionSettled: (payload: SubmitApprovalDecisionPayload) => string | null;
};

export async function submitActionApprovalDecision(
  payload: SubmitApprovalDecisionPayload,
  deps: Dependencies
): Promise<void> {
  try {
    await deps.submitDecision(payload);
  } catch (error) {
    if (
      !(error instanceof LocalBackendRequestError) ||
      error.status !== 409 ||
      error.errorCode !== 'APPROVAL_DECISION_ALREADY_APPLIED'
    ) {
      throw error;
    }
  }
  if (!deps.isResultCurrent()) return;
  // The decision targets the physical process that is waiting, which may be a
  // subagent, but the relay stream and its cursor belong to the Action root, so
  // resume the root process the pause snapshot named. Passing it explicitly keeps
  // the resume attachable after a reconnect cleared the transport's own registries.
  const rootProcessId = deps.onDecisionSettled(payload);
  deps.enqueueResumeRequest({
    kind: 'action',
    actionId: payload.actionId,
    processId: rootProcessId,
    fromStart: false,
  });
}
