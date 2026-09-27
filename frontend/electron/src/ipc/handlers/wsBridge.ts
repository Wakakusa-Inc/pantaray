/**
 * ws:* IPC handlers
 *
 * `ws:send` is fire-and-forget: invalid envelopes are logged via
 * `console.error` and dropped before they reach the WS connection.
 * Validation happens in-process so a malformed renderer event cannot
 * corrupt the orchestration session.
 */

import type { MainContext } from '../context';
import type { IpcRegistrar } from '../registrar';
import { IpcValidationError, parseInput } from '../schemas/error';
import { AcceptActionRequestSchema, OrchestrationClientEventSchema } from '../schemas/ws';

export function registerWsBridgeHandlers(ctx: MainContext, registrar: IpcRegistrar): void {
  registrar.on('ws:send', (_evt, message) => {
    let parsed;
    try {
      parsed = parseInput(OrchestrationClientEventSchema, 'ws:send', message);
    } catch (error) {
      if (error instanceof IpcValidationError) {
        console.error(`[ws:send] dropped invalid payload`, error.issues);
        return;
      }
      throw error;
    }
    Promise.resolve()
      .then(async () => ctx.ws.send(parsed))
      .catch((error) => {
        console.error('[ws:send] transport error', error);
      });
  });

  registrar.handle('ws:acceptAction', async (_evt, request) => {
    const parsed = parseInput(AcceptActionRequestSchema, 'ws:acceptAction', request);
    return await ctx.ws.acceptAction(parsed);
  });

  registrar.handle('ws:getStatus', () => ctx.ws.getStatus());
}
