/**
 * Zod schema for the `actionFile:open` IPC payload.
 */

import path from 'node:path';
import { z } from 'zod';

import { MAX_PATH_LENGTH } from './limits';

export const ActionFileOpenInputSchema = z
  .object({
    path: z
      .string()
      .max(MAX_PATH_LENGTH)
      .refine((value) => path.isAbsolute(value), 'path must be absolute'),
  })
  .strict();

export type ActionFileOpenInput = z.infer<typeof ActionFileOpenInputSchema>;
