const assert = require('assert');
const { test } = require('node:test');
const { submitActionApprovalDecision } = require('../electron/dist/actions/actionApprovalSubmission.js');
const { LocalBackendRequestError } = require('../electron/dist/localBackend/client.js');
const payload = { actionId: 'act-1', processId: 'proc-1-subagent', approvalSessionId: 'approval-1', toolRequestId: 'tool-request-1', decision: 'approved_once' };
const response = { process_id: 'proc-1-subagent', approval_session_id: 'approval-1', decision: 'approved_once', accepted: true };
test('approval settlement is subject-fenced and reconciles only the same canonical decision', async () => {
  const cases = [[null, true, ['settled', 'resume']], [null, false, []], ['APPROVAL_DECISION_ALREADY_APPLIED', true, ['settled', 'resume']], ['APPROVAL_DECISION_CONFLICT', true, null]];
  for (const [errorCode, isCurrent, expectedKinds] of cases) {
    const effects = [];
    const resumeRequests = [];
    const submission = submitActionApprovalDecision(payload, {
      submitDecision: async () => { if (errorCode) throw new LocalBackendRequestError('failed', 409, errorCode); return response; },
      isResultCurrent: () => isCurrent,
      onDecisionSettled: () => { effects.push('settled'); return 'proc-1-root'; },
      enqueueResumeRequest: (request) => { effects.push('resume'); resumeRequests.push(request); },
    });
    if (expectedKinds === null) await assert.rejects(submission, /failed/);
    else {
      await submission;
      assert.deepStrictEqual(effects, expectedKinds);
      // 決定は子 process へ送るが、relay の再開先は settle が返す root Action transport。
      assert.deepStrictEqual(resumeRequests, expectedKinds.includes('resume')
        ? [{ kind: 'action', actionId: 'act-1', processId: 'proc-1-root', fromStart: false }]
        : []);
    }
  }
});

test('root transport が未知でも resume は actionId 解決へフォールバックする', async () => {
  const resumeRequests = [];
  await submitActionApprovalDecision(payload, {
    submitDecision: async () => response,
    isResultCurrent: () => true,
    onDecisionSettled: () => null,
    enqueueResumeRequest: (request) => resumeRequests.push(request),
  });
  assert.deepStrictEqual(resumeRequests, [
    { kind: 'action', actionId: 'act-1', processId: null, fromStart: false },
  ]);
});
