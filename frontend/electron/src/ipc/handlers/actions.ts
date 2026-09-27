import type { IpcMainInvokeEvent } from 'electron';

import type { MainContext } from '../context';
import type { IpcRegistrar } from '../registrar';
import { IpcSenderRejectedError } from '../senderTrust';
import type {
  ActionMessageResponse,
  ActionMessageSubmitResult,
} from '../../actions/actionContracts';
import { LocalBackendRequestError } from '../../localBackend/client';
import {
  ActionConversationPageRequestSchema,
  ActionMessageRequestSchema,
  ActionResumeRequestSchema,
  ActionToolOutputRequestSchema,
} from '../schemas/actions';
import { parseInput } from '../schemas/error';

/**
 * ひとつの USER ターンを開く要求を、その結果の引き回しごと実行する。
 *
 * 送信と「再開」は同じターンの開き方なので、409 の読み替えも、オーバーレイとの
 * 対応付けも、新しい process への live relay の張り直しも同じでなければならない。
 */
async function openUserTurn(
  ctx: MainContext,
  event: IpcMainInvokeEvent,
  open: () => Promise<ActionMessageResponse>
): Promise<ActionMessageSubmitResult> {
  const overlayId = ctx.actions.resolveOverlayIdForSender(event.sender);
  if (overlayId === null) throw new IpcSenderRejectedError('overlay_window_not_registered');
  const subjectId = ctx.actions.getCurrentSubjectId();
  if (subjectId === null) throw new Error('Missing authenticated user id.');
  let response: ActionMessageResponse;
  try {
    response = await open();
  } catch (error) {
    if (error instanceof LocalBackendRequestError && error.status === 409) {
      if (error.errorCode === 'ExpectedProcessConflict') {
        return { kind: 'expected_process_conflict' } satisfies ActionMessageSubmitResult;
      }
      if (error.errorCode === 'ActionConflict') {
        return { kind: 'action_conflict' } satisfies ActionMessageSubmitResult;
      }
    }
    throw error;
  }
  if (
    ctx.actions.getCurrentSubjectId() === subjectId &&
    ctx.actions.resolveOverlayIdForSender(event.sender) === overlayId
  ) {
    ctx.actions.registerActionAssociation(response.action_id, overlayId);
    ctx.actions.refreshActionConversation(response.action_id);
    if (response.disposition === 'started') {
      // A standalone (or follow-up) HTTP submit starts a new backend process
      // with no other live-relay attach path, so request the resume here or
      // the overlay never receives lifecycle, pause, or step events.
      ctx.overlay.resumeLiveProcess({
        kind: 'action',
        processId: response.process_id,
        actionId: response.action_id,
        fromStart: true,
      });
    }
  }
  return { kind: 'submitted', response } satisfies ActionMessageSubmitResult;
}

export function registerActionHandlers(ctx: MainContext, registrar: IpcRegistrar): void {
  registrar.handle('action:submitMessage', async (event, request) =>
    openUserTurn(ctx, event, () =>
      ctx.actions.submitMessage(
        parseInput(ActionMessageRequestSchema, 'action:submitMessage', request)
      )
    )
  );
  registrar.handle('action:resume', async (event, request) =>
    openUserTurn(ctx, event, () =>
      ctx.actions.resumeAction(parseInput(ActionResumeRequestSchema, 'action:resume', request))
    )
  );
  registrar.handle('action:readConversationPage', async (_event, request) => {
    const parsed = parseInput(
      ActionConversationPageRequestSchema,
      'action:readConversationPage',
      request
    );
    try {
      return await ctx.actions.readConversationPage(parsed);
    } catch (error) {
      if (
        parsed.cursor !== null &&
        error instanceof LocalBackendRequestError &&
        error.status === 409
      ) {
        return { kind: 'stale_cursor' } as const;
      }
      throw error;
    }
  });
  registrar.handle('action:readToolOutputPage', async (_event, request) =>
    ctx.actions.readToolOutputPage(
      parseInput(ActionToolOutputRequestSchema, 'action:readToolOutputPage', request)
    )
  );
}
