import type { LocalRuntimeState } from '../auth/localRuntimeState';
import { LocalBackendRequestError } from '../localBackend/client';
import {
  ConversationHistoryPageSchema,
  ConversationHistoryRequestSchema,
  type ConversationHistoryListItem,
} from './historyContracts';

const HISTORY_REQUEST_TIMEOUT_MS = 30_000;
const INVALID_HISTORY_RESPONSE_MESSAGE = 'Invalid conversation history response.';

export type HistoryFetchResult = {
  data: ConversationHistoryListItem[];
  nextCursor: string | null;
  unreadActionIds: string[];
  error: string | null;
  errorCode: string | null;
};

type HistoryRequestJson = <T>(request: {
  path: string;
  method: 'GET';
  query: Record<string, string | number | null>;
  timeoutMs: number;
}) => Promise<T>;

const failedResult = (error: unknown): HistoryFetchResult => ({
  data: [],
  nextCursor: null,
  unreadActionIds: [],
  error:
    error instanceof Error && error.name !== 'ZodError'
      ? error.message
      : INVALID_HISTORY_RESPONSE_MESSAGE,
  errorCode: error instanceof LocalBackendRequestError ? error.errorCode : null,
});

export function createHistoryFetcher(params: {
  requestJson: HistoryRequestJson;
  getRuntimeState: () => LocalRuntimeState;
  getCompletionUnreadSnapshot: () => (
    actionId: string,
    completionEventId: string | null
  ) => boolean;
}): (input: unknown) => Promise<HistoryFetchResult> {
  return async function historyFetchFromMain(input: unknown): Promise<HistoryFetchResult> {
    try {
      const request = ConversationHistoryRequestSchema.parse(input);
      const runtimeState = params.getRuntimeState();
      if (runtimeState.status !== 'ready' || !runtimeState.owner) {
        throw new Error('Local owner is unavailable.');
      }
      const isCompletionUnread = params.getCompletionUnreadSnapshot();
      const payload = await params.requestJson<unknown>({
        path: '/api/agent/history',
        method: 'GET',
        query: {
          cursor: request.cursor,
          limit: request.limit,
          search_text: request.filters.searchText,
        },
        timeoutMs: HISTORY_REQUEST_TIMEOUT_MS,
      });
      // Wiring replaces this snapshot on every transition, including A -> B -> A.
      if (params.getRuntimeState() !== runtimeState) throw new Error('Local owner changed.');
      const page = ConversationHistoryPageSchema.parse(payload);
      const unreadActionIds = page.items.flatMap((item) =>
        item.kind === 'conversation' &&
        item.status === 'idle' &&
        item.latest_completion_event_id !== null &&
        isCompletionUnread(item.action_id, item.latest_completion_event_id)
          ? [item.action_id]
          : []
      );
      return {
        data: page.items,
        nextCursor: page.next_cursor,
        unreadActionIds,
        error: null,
        errorCode: null,
      };
    } catch (error) {
      return failedResult(error);
    }
  };
}
