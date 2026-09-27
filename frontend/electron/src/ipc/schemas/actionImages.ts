/**
 * `action:attachImage` / `actionImage:reveal` payload contracts.
 *
 * Shared by Electron main (validation) and the renderer composer (pre-flight limits), so a
 * rejection the user can avoid is shown before 8 MB crosses the IPC boundary.
 */

import { z } from 'zod';

import { ACTION_IMAGE_MIME_TYPES } from '../../protocol/imageStoragePath';

/** `AGENT_SCREENCAPTURE_MAX_BYTES_PER_IMAGE` (local backend runtime bundle). */
export const ACTION_IMAGE_MAX_BYTES = 8_000_000;
/** `AGENT_SCREENCAPTURE_MAX_COUNT`: images the runtime passes to the model per request. */
export const ACTION_IMAGE_MAX_PER_MESSAGE = 10;
/** `IMAGE_MAX_DECODED_PIXELS_PER_REQUEST` (cloud proxy media projection). */
export const ACTION_IMAGE_MAX_DECODED_PIXELS = 64_000_000;

export const ActionImageAttachInputSchema = z
  .object({
    bytes: z.instanceof(ArrayBuffer).refine((value) => value.byteLength > 0, 'image is empty'),
    declaredMimeType: z.enum(ACTION_IMAGE_MIME_TYPES),
  })
  .strict();

export const ActionImageRevealInputSchema = z.object({ storagePath: z.string().min(1) }).strict();

export type ActionImageAttachRejectionReason =
  | 'unsupported_media_type'
  | 'too_large'
  | 'decode_failed';

export type ActionImageAttachResult =
  | Readonly<{
      kind: 'attached';
      storagePath: string;
      mimeType: string;
      byteSize: number;
      sha256: string;
      widthPx: number;
      heightPx: number;
    }>
  | Readonly<{ kind: 'rejected'; reason: ActionImageAttachRejectionReason }>;
