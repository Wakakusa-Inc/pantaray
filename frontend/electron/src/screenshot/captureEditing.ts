/** An editor may release only its own pause, including while its owner is syncing. */
export type CaptureEditingRequest =
  | { kind: 'begin'; ownerId: string; sessionId: string }
  | { kind: 'end'; sessionId: string };
