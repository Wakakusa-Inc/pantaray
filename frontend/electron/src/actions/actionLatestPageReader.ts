import type { ActionConversationPage } from './actionContracts';

type ReadState = { active: boolean; dirty: boolean };
type ReadFlight = { state: ReadState; promise: Promise<ActionConversationPage> };

export function createActionLatestPageReader(
  readLatestPage: (actionId: string) => Promise<ActionConversationPage>
): {
  read: (actionId: string) => Promise<ActionConversationPage>;
  clear: () => void;
} {
  const flights = new Map<string, ReadFlight>();

  const read = (actionId: string): Promise<ActionConversationPage> => {
    const existing = flights.get(actionId);
    if (existing) {
      existing.state.dirty = true;
      return existing.promise;
    }

    const state: ReadState = { active: true, dirty: false };
    const promise = (async () => {
      while (true) {
        try {
          const page = await readLatestPage(actionId);
          if (!state.active || !state.dirty) return page;
        } catch (error) {
          if (!state.active || !state.dirty) throw error;
        }
        state.dirty = false;
      }
    })().finally(() => {
      if (flights.get(actionId)?.state === state) flights.delete(actionId);
    });
    flights.set(actionId, { state, promise });
    return promise;
  };

  return {
    read,
    clear: () => {
      for (const flight of flights.values()) flight.state.active = false;
      flights.clear();
    },
  };
}
