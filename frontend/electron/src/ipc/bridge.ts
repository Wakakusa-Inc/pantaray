/**
 * IPC allowlist 判定ロジック（純関数）
 *
 * 目的:
 * - preload の「許可/拒否」挙動をユニットテスト可能にする。
 * - main/preload で同じ判定を再利用できるようにする。
 */

import type { ValidInvokeChannel, ValidReceiveChannel, ValidSendChannel } from './channels';
import { validInvokeChannels, validReceiveChannels, validSendChannels } from './channels';

function includes<T extends string>(list: readonly T[], value: string): value is T {
  // NOTE: `Array.prototype.includes` の返り値を型ガード化するための補助
  return (list as readonly string[]).includes(value);
}

export function isValidSendChannel(channel: unknown): channel is ValidSendChannel {
  return typeof channel === 'string' && includes(validSendChannels, channel);
}

export function isValidReceiveChannel(channel: unknown): channel is ValidReceiveChannel {
  return typeof channel === 'string' && includes(validReceiveChannels, channel);
}

function isValidInvokeChannel(channel: unknown): channel is ValidInvokeChannel {
  return typeof channel === 'string' && includes(validInvokeChannels, channel);
}

/**
 * invoke は「明示的に拒否」する（fail-closed）。
 */
export function assertValidInvokeChannel(channel: unknown): asserts channel is ValidInvokeChannel {
  if (!isValidInvokeChannel(channel)) {
    throw new Error(`Unauthorized IPC channel: ${String(channel)}`);
  }
}
