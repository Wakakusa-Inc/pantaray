/** A project named in the draft; `start`/`end` are UTF-16 offsets into the raw draft. */
export type ComposerMention = Readonly<{
  projectId: string;
  displayName: string;
  paths: readonly string[];
  start: number;
  end: number;
}>;

export type MentionTrigger = Readonly<{ start: number; query: string }>;

const TRIGGER_CHARACTERS = new Set(['@', '＠']);

/**
 * The `@` (or full-width `＠`) the caret is typing after, with the text typed since. Any
 * position on any line counts; whitespace between the trigger and the caret ends it.
 */
export function findMentionTrigger(draft: string, caret: number): MentionTrigger | null {
  for (let index = Math.min(caret, draft.length) - 1; index >= 0; index -= 1) {
    const character = draft[index];
    if (TRIGGER_CHARACTERS.has(character)) {
      return { start: index, query: draft.slice(index + 1, caret) };
    }
    if (/\s/.test(character)) return null;
  }
  return null;
}

/**
 * Carry mentions across one edit (the span between common prefix and suffix): a mention it
 * touches becomes plain text, a later one shifts. Every kept mention still spells its name.
 */
export function rebaseMentions(
  previous: string,
  next: string,
  mentions: readonly ComposerMention[]
): ComposerMention[] {
  if (previous === next) return [...mentions];
  const shorter = Math.min(previous.length, next.length);
  let prefix = 0;
  while (prefix < shorter && previous[prefix] === next[prefix]) prefix += 1;
  let suffix = 0;
  while (
    suffix < shorter - prefix &&
    previous[previous.length - 1 - suffix] === next[next.length - 1 - suffix]
  ) {
    suffix += 1;
  }
  const editedEnd = previous.length - suffix;
  const delta = next.length - previous.length;
  return mentions.flatMap((mention) => {
    if (mention.end <= prefix) return [mention];
    if (mention.start >= editedEnd) {
      return [{ ...mention, start: mention.start + delta, end: mention.end + delta }];
    }
    return [];
  });
}

export type ComposerEdit = Readonly<{
  draft: string;
  mentions: ComposerMention[];
  caret: number;
}>;

/** Replace the trigger and its query with the project name followed by one space. */
export function insertMention(
  draft: string,
  mentions: readonly ComposerMention[],
  trigger: MentionTrigger,
  project: Omit<ComposerMention, 'start' | 'end'>
): ComposerEdit {
  const queryEnd = trigger.start + 1 + trigger.query.length;
  const end = trigger.start + project.displayName.length;
  const next = `${draft.slice(0, trigger.start)}${project.displayName} ${draft.slice(queryEnd)}`;
  return {
    draft: next,
    mentions: [...rebaseMentions(draft, next, mentions), { ...project, start: trigger.start, end }]
      // The backend requires spans in text order.
      .sort((left, right) => left.start - right.start),
    caret: end + 1,
  };
}

/** Backspace right after a project name removes the whole name, not its last character. */
export function removeMentionBefore(
  draft: string,
  mentions: readonly ComposerMention[],
  caret: number
): ComposerEdit | null {
  const target = mentions.find((mention) => mention.end === caret);
  if (!target) return null;
  const next = draft.slice(0, target.start) + draft.slice(target.end);
  return {
    draft: next,
    mentions: rebaseMentions(draft, next, mentions),
    caret: target.start,
  };
}

export function mentionOptionId(listId: string, index: number): string {
  return `${listId}-option-${index}`;
}
