/**
 * Zod schemas for `privacy:*` IPC payloads.
 *
 * The renderer round-trips settings: it fetches normalized settings from main,
 * mutates them in the UI, and sends them back. Schemas mirror the canonical shape in
 * `privacy/capturePrivacy.ts`; the SSOT normalizes again after validation.
 */

import { z } from 'zod';
import type { CaptureEditingRequest } from '../../screenshot/captureEditing';

import {
  MAX_ARRAY_LENGTH,
  MAX_DISPLAY_NAME_LENGTH,
  MAX_HOST_LENGTH,
  MAX_ID_LENGTH,
} from './limits';

const TrimmedNonEmpty = (max: number) => z.string().trim().min(1).max(max);

const CaptureFilterModeSchema = z.enum(['exclude', 'include_only']);

const CaptureAppEntrySchema = z.object({
  name: TrimmedNonEmpty(MAX_DISPLAY_NAME_LENGTH),
  bundleId: TrimmedNonEmpty(MAX_ID_LENGTH).nullable(),
});

export const IdeFileRulesSchema = z.object({
  mode: z.enum(['off', 'on']),
  onFileNameUnavailable: z.enum(['block', 'allow']),
  sensitivePresets: z.object({
    blockEnvFiles: z.boolean(),
  }),
});

// `ideFileRules` is optional because the filter dialog saves the app and website lists
// alone; the SSOT keeps the stored IDE rules when it is omitted.
export const CapturePrivacySettingsSchema = z.object({
  version: z.literal(2),
  apps: z.object({
    mode: CaptureFilterModeSchema,
    entries: z.array(CaptureAppEntrySchema).max(MAX_ARRAY_LENGTH),
  }),
  websites: z.object({
    mode: CaptureFilterModeSchema,
    hosts: z.array(TrimmedNonEmpty(MAX_HOST_LENGTH)).max(MAX_ARRAY_LENGTH),
  }),
  ideFileRules: IdeFileRulesSchema.optional(),
});

export const CaptureEditingSchema = z.discriminatedUnion('kind', [
  z
    .object({
      kind: z.literal('begin'),
      ownerId: TrimmedNonEmpty(MAX_ID_LENGTH),
      sessionId: z.string().uuid(),
    })
    .strict(),
  z.object({ kind: z.literal('end'), sessionId: z.string().uuid() }).strict(),
]) satisfies z.ZodType<CaptureEditingRequest>;

export type CapturePrivacySettingsInput = z.infer<typeof CapturePrivacySettingsSchema>;
export type IdeFileRulesInput = z.infer<typeof IdeFileRulesSchema>;
