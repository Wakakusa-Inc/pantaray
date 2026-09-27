/** Wire types for the existing authenticated local backend control API. */
export type SourceStopReason = 'disabled' | 'signed_out' | 'policy_change' | 'shutdown';
export type SourceBlockedReason =
  | 'permission_required'
  | 'key_unavailable'
  | 'recorder_unavailable'
  | 'protocol_incompatible';

export type RecorderBinding = Readonly<{
  store_id: string;
  protocol_version: 1;
}>;

export type SourceBinding = RecorderBinding &
  Readonly<{
    user_id: string;
    epoch: string;
    policy_revision: string;
  }>;

export type SourceState =
  | Readonly<{
      kind: 'stopped';
      epoch: string;
      policy_revision: string;
      reason: SourceStopReason;
    }>
  | Readonly<{ kind: 'starting'; epoch: string; policy_revision: string }>
  | Readonly<{ kind: 'ready'; binding: SourceBinding; capture_paused?: boolean }>
  | SourceBlocked;

export type SourceBlocked = Readonly<{
  kind: 'blocked';
  epoch: string;
  policy_revision: string;
  reason: SourceBlockedReason;
}>;

export type SourceTransition =
  | Readonly<{
      kind: 'suspend';
      request_id: string;
      expected_epoch: string;
      reason: SourceStopReason;
      policy_revision: string;
    }>
  | Readonly<{
      kind: 'activate';
      request_id: string;
      /** Issued by suspend; must equal the current epoch. Activation keeps it. */
      issued_epoch: string;
      recorder_binding: RecorderBinding;
      /** Recording is off: the source becomes ready and paused in one transition. */
      capture_paused: boolean;
    }>
  | Readonly<{
      /** Turns capture off or on; the generation, binding and read permit stay. */
      kind: 'set_capture_paused';
      request_id: string;
      expected_epoch: string;
      paused: boolean;
    }>;

export type SourceTransitionResult =
  | Readonly<{ kind: 'applied'; state: Exclude<SourceState, SourceBlocked> }>
  | Readonly<{
      kind: 'conflict';
      current_epoch: string;
      reason: 'stale_epoch' | 'request_id_reused';
    }>
  | Readonly<{ kind: 'blocked'; state: SourceBlocked }>;
