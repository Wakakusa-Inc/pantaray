import type { ActionToolOutputDetail } from './actionContracts';
import type { ActionToolOutputRequest } from './actionFetch';

export const ACTION_TOOL_OUTPUT_PAGE_LIMIT_BYTES = 65_536;

export type ActionToolOutputKey = Readonly<{
  actionId: string;
  stepId: string;
}>;

export type LoadedActionToolOutput =
  | Readonly<{ kind: 'text'; content: string; truncated: boolean }>
  | Readonly<{ kind: 'unavailable'; reason: 'no_output' | 'binary' }>;

export type ActionToolOutputPageReader = (
  request: ActionToolOutputRequest
) => Promise<ActionToolOutputDetail>;

export type ActionToolOutputLoader = Readonly<{
  load: (key: ActionToolOutputKey) => Promise<LoadedActionToolOutput>;
  retry: (key: ActionToolOutputKey) => Promise<LoadedActionToolOutput>;
  clear: () => void;
}>;

export class ActionToolOutputPaginationError extends Error {
  constructor() {
    super('Action tool output pagination repeated a cursor.');
    this.name = 'ActionToolOutputPaginationError';
  }
}

function exactKey(key: ActionToolOutputKey): string {
  return JSON.stringify([key.actionId, key.stepId]);
}

async function readAllPages(
  readPage: ActionToolOutputPageReader,
  key: ActionToolOutputKey
): Promise<LoadedActionToolOutput> {
  const chunks: string[] = [];
  const cursors = new Set<string>();
  let cursor: string | null = null;

  while (true) {
    const page = await readPage({
      actionId: key.actionId,
      stepId: key.stepId,
      cursor,
      limitBytes: ACTION_TOOL_OUTPUT_PAGE_LIMIT_BYTES,
    });
    if (page.unavailable_reason !== null) {
      return { kind: 'unavailable', reason: page.unavailable_reason };
    }
    chunks.push(page.content);
    if (page.next_cursor === null) {
      return { kind: 'text', content: chunks.join(''), truncated: page.truncated };
    }
    if (cursors.has(page.next_cursor)) throw new ActionToolOutputPaginationError();
    cursors.add(page.next_cursor);
    cursor = page.next_cursor;
  }
}

export function createActionToolOutputLoader(
  readPage: ActionToolOutputPageReader
): ActionToolOutputLoader {
  const loads = new Map<string, Promise<LoadedActionToolOutput>>();

  const load = (key: ActionToolOutputKey): Promise<LoadedActionToolOutput> => {
    const cacheKey = exactKey(key);
    const existing = loads.get(cacheKey);
    if (existing) return existing;
    const pending = readAllPages(readPage, key);
    loads.set(cacheKey, pending);
    return pending;
  };

  return {
    load,
    retry: (key) => {
      loads.delete(exactKey(key));
      return load(key);
    },
    clear: () => loads.clear(),
  };
}
