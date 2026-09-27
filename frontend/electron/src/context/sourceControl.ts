export type RecorderBinding = { store_id: string; protocol_version: 1 };
export type StopReason = 'disabled' | 'signed_out' | 'policy_change' | 'shutdown';
type SourceReady = {
  kind: 'ready';
  binding: RecorderBinding & {
    user_id: string;
    epoch: string;
    policy_revision: string;
  };
  /** Recording is turned off: the recorder keeps its permit and records nothing. */
  capture_paused?: boolean;
};
type SourceStopped = {
  kind: 'stopped';
  epoch: string;
  policy_revision: string;
  reason: StopReason;
};
type SourceStarting = { kind: 'starting'; epoch: string; policy_revision: string };
type SourceBlocked = {
  kind: 'blocked';
  epoch: string;
  policy_revision: string;
  reason:
    | 'permission_required'
    | 'key_unavailable'
    | 'recorder_unavailable'
    | 'protocol_incompatible';
};
export type SourceState = SourceReady | SourceStopped | SourceStarting | SourceBlocked;
export type SourceTransition =
  | {
      kind: 'suspend';
      request_id: string;
      expected_epoch: string;
      reason: StopReason;
      policy_revision: string;
    }
  | {
      kind: 'activate';
      request_id: string;
      issued_epoch: string;
      recorder_binding: RecorderBinding;
      /** Recording is off: the source becomes ready and paused in one transition. */
      capture_paused: boolean;
    }
  | {
      /** Turns capture off or on; the generation, binding and read permit stay. */
      kind: 'set_capture_paused';
      request_id: string;
      expected_epoch: string;
      paused: boolean;
    };
export type SourceTransitionResult =
  | { kind: 'applied'; state: SourceReady | SourceStopped | SourceStarting }
  | { kind: 'conflict'; current_epoch: string; reason: 'stale_epoch' | 'request_id_reused' }
  | { kind: 'blocked'; state: SourceBlocked };
