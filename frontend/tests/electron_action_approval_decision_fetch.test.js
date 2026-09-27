const assert = require('assert');
const { test } = require('node:test');

const {
  ActionApprovalDecisionResponseError,
  createActionApprovalDecisionFetcher,
} = require('../electron/dist/actions/actionApprovalDecisionFetch.js');
const { LocalBackendRequestError } = require('../electron/dist/localBackend/client.js');

test('approval decision fetcher は requestJson に canonical payload を渡す', async () => {
  /** @type {Array<unknown>} */
  const calls = [];
  const submitApprovalDecision = createActionApprovalDecisionFetcher({
    getUserId: () => 'user-1',
    requestJson: async (request) => {
      calls.push(request);
      return {
        process_id: 'proc-1',
        approval_session_id: 'approval-1',
        decision: 'approved_once',
        accepted: true,
      };
    },
  });

  const result = await submitApprovalDecision({
    actionId: 'act-1',
    processId: 'proc-1',
    approvalSessionId: 'approval-1',
    toolRequestId: 'tool-request-1',
    decision: 'approved_once',
  });

  assert.equal(calls.length, 1);
  assert.deepStrictEqual(calls[0], {
    path: '/v1/agents/users/user-1/actions/act-1/approvals',
    method: 'POST',
    body: {
      process_id: 'proc-1',
      decision: 'approved_once',
      tool_request_id: 'tool-request-1',
      approval_session_id: 'approval-1',
    },
  });
  assert.equal(result.process_id, 'proc-1');
});

test('approval decision fetcher は local backend error_code を保持する', async () => {
  const submitApprovalDecision = createActionApprovalDecisionFetcher({
    getUserId: () => 'user-1',
    requestJson: async () => {
      throw new LocalBackendRequestError('stale overlay', 409, 'APPROVAL_DECISION_CONFLICT');
    },
  });

  await assert.rejects(
    () =>
      submitApprovalDecision({
        actionId: 'act-1',
        processId: 'proc-1',
        approvalSessionId: 'approval-1',
        toolRequestId: 'tool-request-1',
        decision: 'approved_once',
      }),
    /** @param {unknown} error */
    (error) =>
      error instanceof LocalBackendRequestError &&
      error.status === 409 &&
      error.errorCode === 'APPROVAL_DECISION_CONFLICT'
  );
});

test('approval decision fetcher は別processの成功応答を拒否する', async () => {
  const submitApprovalDecision = createActionApprovalDecisionFetcher({
    getUserId: () => 'user-1',
    requestJson: async () => ({
      process_id: 'other-process',
      approval_session_id: 'approval-1',
      decision: 'approved_once',
      accepted: true,
    }),
  });

  await assert.rejects(
    () =>
      submitApprovalDecision({
        actionId: 'act-1',
        processId: 'proc-1',
        approvalSessionId: 'approval-1',
        toolRequestId: 'tool-request-1',
        decision: 'approved_once',
      }),
    (error) => error instanceof ActionApprovalDecisionResponseError
  );
});

test('approval decision fetcher は会話単位の許可の応答を受け取る', async () => {
  const submitApprovalDecision = createActionApprovalDecisionFetcher({
    getUserId: () => 'user-1',
    requestJson: async () => ({
      process_id: 'proc-1',
      approval_session_id: 'approval-1',
      decision: 'approved_for_conversation',
      accepted: true,
    }),
  });

  const result = await submitApprovalDecision({
    actionId: 'act-1',
    processId: 'proc-1',
    approvalSessionId: 'approval-1',
    toolRequestId: 'tool-request-1',
    decision: 'approved_for_conversation',
  });

  assert.equal(result.decision, 'approved_for_conversation');
});
