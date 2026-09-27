import { randomUUID } from 'crypto';
import fs from 'fs';
import path from 'path';
import { z } from 'zod';

import { resolveScopedSettingsPath } from '../settings/scope';

const ACTION_READ_STATE_FILE_NAME = 'action-read-state.json';
const ACTION_READ_STATE_VERSION = 1;
const ACTION_READ_STATE_MAX_ENTRIES = 1_000;

const canonicalIdentitySchema = z
  .string()
  .refine((value) => value.length > 0 && value === value.trim());
const ActionReadStateEntrySchema = z
  .object({
    action_id: canonicalIdentitySchema,
    completion_event_id: canonicalIdentitySchema,
  })
  .strict();
const ActionReadStateFileSchema = z
  .object({
    version: z.literal(ACTION_READ_STATE_VERSION),
    entries: z.array(ActionReadStateEntrySchema).max(ACTION_READ_STATE_MAX_ENTRIES),
  })
  .strict()
  .refine(
    ({ entries }) => new Set(entries.map((entry) => entry.action_id)).size === entries.length
  );

type ActionReadStateEntry = z.infer<typeof ActionReadStateFileSchema>['entries'][number];

export const ActionCompletionViewedRequestSchema = z
  .object({
    subjectId: canonicalIdentitySchema,
    actionId: canonicalIdentitySchema,
    completionEventId: canonicalIdentitySchema,
  })
  .strict();
export type ActionCompletionViewedRequest = z.infer<typeof ActionCompletionViewedRequestSchema>;

type ActionReadStateScope = {
  subjectId: string;
  path: string;
  entries: ActionReadStateEntry[];
};

export type ActionReadState = {
  setSubject: (userId: string | null) => void;
  snapshotCompletionUnread: () => (actionId: string, completionEventId: string | null) => boolean;
  markCompletionViewed: (request: ActionCompletionViewedRequest) => void;
};

function readEntries(settingsPath: string): ActionReadStateEntry[] {
  let serialized: string;
  try {
    serialized = fs.readFileSync(settingsPath, 'utf8');
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return [];
    throw error;
  }
  try {
    const result = ActionReadStateFileSchema.safeParse(JSON.parse(serialized));
    return result.success ? result.data.entries : [];
  } catch (error) {
    if (error instanceof SyntaxError) return [];
    throw error;
  }
}

function writeEntriesAtomically(settingsPath: string, entries: ActionReadStateEntry[]): void {
  const temporaryPath = path.join(
    path.dirname(settingsPath),
    `.${path.basename(settingsPath)}.${process.pid}.${randomUUID()}.tmp`
  );
  const payload = JSON.stringify({ version: ACTION_READ_STATE_VERSION, entries });
  let fileDescriptor: number | null = null;
  try {
    fileDescriptor = fs.openSync(temporaryPath, 'wx', 0o600);
    fs.writeFileSync(fileDescriptor, payload, 'utf8');
    fs.fsyncSync(fileDescriptor);
    fs.closeSync(fileDescriptor);
    fileDescriptor = null;
    fs.renameSync(temporaryPath, settingsPath);
  } catch (error) {
    if (fileDescriptor !== null) {
      try {
        fs.closeSync(fileDescriptor);
      } catch {
        // Preserve the write failure that owns this cleanup path.
      }
    }
    try {
      fs.unlinkSync(temporaryPath);
    } catch {
      // Preserve the write failure that owns this cleanup path.
    }
    throw error;
  }
}

export function createActionReadState(params: { userDataDir: string }): ActionReadState {
  let scope: ActionReadStateScope | null = null;

  return {
    setSubject: (userId) => {
      if (userId === null) {
        scope = null;
        return;
      }
      const nextPath = resolveScopedSettingsPath({
        userDataDir: params.userDataDir,
        userId,
        fileName: ACTION_READ_STATE_FILE_NAME,
      });
      scope = { subjectId: userId, path: nextPath, entries: readEntries(nextPath) };
    },
    snapshotCompletionUnread: () => {
      const snapshotScope = scope;
      return (actionId, completionEventId) => {
        if (snapshotScope === null || completionEventId === null) return false;
        return !snapshotScope.entries.some(
          (entry) => entry.action_id === actionId && entry.completion_event_id === completionEventId
        );
      };
    },
    markCompletionViewed: ({ subjectId, actionId, completionEventId }) => {
      if (scope === null || scope.subjectId !== subjectId) {
        throw new Error('Action read state subject does not match the authenticated subject.');
      }
      const entry: ActionReadStateEntry = {
        action_id: actionId,
        completion_event_id: completionEventId,
      };
      const candidate = [
        ...scope.entries.filter((current) => current.action_id !== actionId),
        entry,
      ].slice(-ACTION_READ_STATE_MAX_ENTRIES);
      writeEntriesAtomically(scope.path, candidate);
      scope.entries = candidate;
    },
  };
}
