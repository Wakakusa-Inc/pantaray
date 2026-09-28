import { describe, expect, it } from 'vitest';
import {
  findMentionTrigger,
  insertMention,
  rebaseMentions,
  removeMentionBefore,
  type ComposerMention,
} from './composerMentions';

const aurora = { projectId: 'p-aurora', displayName: 'Aurora', paths: ['/Users/demo/aurora'] };

function mention(start: number, displayName = 'Aurora'): ComposerMention {
  return { ...aurora, displayName, start, end: start + displayName.length };
}

describe('findMentionTrigger', () => {
  it('opens after @ anywhere on any line, including full-width ＠ glued to text', () => {
    expect(findMentionTrigger('mail@au', 7)).toEqual({ start: 4, query: 'au' });
    expect(findMentionTrigger('first line\n＠北極', 14)).toEqual({ start: 11, query: '北極' });
  });

  it('closes on whitespace between the trigger and the caret, or a caret before it', () => {
    expect(findMentionTrigger('@au ra', 6)).toBeNull();
    expect(findMentionTrigger('@au\nra', 6)).toBeNull();
    expect(findMentionTrigger('ab@cd', 2)).toBeNull();
  });
});

describe('rebaseMentions', () => {
  const draft = 'see Aurora now';
  const mentions = [mention(4)];

  it('shifts a mention after an edit before it and keeps it when typing right after it', () => {
    expect(rebaseMentions(draft, `please ${draft}`, mentions)).toEqual([mention(11)]);
    expect(rebaseMentions(draft, 'see Aurora, now', mentions)).toEqual(mentions);
  });

  it('turns a mention back into text when the edit touches it', () => {
    expect(rebaseMentions(draft, 'see Aurxora now', mentions)).toEqual([]);
    expect(rebaseMentions(draft, 'see Auror now', mentions)).toEqual([]);
    expect(rebaseMentions(draft, 'see now', mentions)).toEqual([]);
  });
});

describe('insertMention', () => {
  it('replaces @ and the query with the name and one space, keeping spans ordered', () => {
    const draft = 'x @au y Aurora';
    const edit = insertMention(draft, [mention(8)], { start: 2, query: 'au' }, aurora);
    expect(edit.draft).toBe('x Aurora  y Aurora');
    expect(edit.caret).toBe(9);
    expect(edit.mentions).toEqual([mention(2), mention(12)]);
  });
});

describe('removeMentionBefore', () => {
  it('removes the whole name right before the caret and shifts later mentions', () => {
    const edit = removeMentionBefore('Aurora and Nimbus', [mention(0), mention(11, 'Nimbus')], 6);
    expect(edit).toEqual({ draft: ' and Nimbus', mentions: [mention(5, 'Nimbus')], caret: 0 });
    expect(removeMentionBefore('Aurora ', [mention(0)], 7)).toBeNull();
  });
});
