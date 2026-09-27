import { z } from 'zod';

const STORAGE_PREFIX = 'pantaray.conversation-scroll:';
const positionSchema = z.object({
  top: z.number().finite().nonnegative(),
  atBottom: z.boolean(),
  pageCount: z.number().int().positive(),
});
export type ConversationScrollPosition = z.infer<typeof positionSchema>;

// Only layout coordinates and the opaque Action ID are stored, never conversation content.
export function readConversationScrollPosition(actionId: string) {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + actionId);
    if (raw === null) return null;
    const result = positionSchema.safeParse(JSON.parse(raw));
    return result.success ? result.data : null;
  } catch (error) {
    if (!(error instanceof SyntaxError || error instanceof DOMException)) throw error;
    console.warn('Conversation scroll position could not be read.');
    return null;
  }
}

export function saveConversationScrollPosition(
  actionId: string,
  position: ConversationScrollPosition
) {
  try {
    localStorage.setItem(STORAGE_PREFIX + actionId, JSON.stringify(position));
  } catch (error) {
    if (!(error instanceof DOMException)) throw error;
    console.warn('Conversation scroll position could not be saved.');
  }
}

export function clearConversationScrollPositions() {
  try {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith(STORAGE_PREFIX)) localStorage.removeItem(key);
    }
  } catch (error) {
    if (!(error instanceof DOMException)) throw error;
    console.warn('Conversation scroll positions could not be cleared.');
  }
}
