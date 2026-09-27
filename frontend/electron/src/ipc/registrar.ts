/**
 * IPC 登録ユーティリティ（main 側）
 *
 * 目的:
 * - `ipcMain.handle/on` の登録を 1 箇所に集約し、登録チャンネルを追跡できるようにする。
 * - チャンネル名は allowlist（`channels.ts`）の型で縛り、未許可チャンネルの登録をコンパイル時に防ぐ。
 * - `dispose()` で登録解除できるようにし、node:test で回帰テストしやすくする。
 */

import type { IpcMain, IpcMainEvent, IpcMainInvokeEvent } from 'electron';

import type { ValidInvokeChannel, ValidSendChannel } from './channels';
import {
  IpcSenderRejectedError,
  type IpcChannel,
  type IpcSenderEvent,
  type IpcWindowRole,
} from './senderTrust';

export type IpcMainLike = Pick<IpcMain, 'handle' | 'on' | 'removeHandler' | 'removeListener'>;

export type InvokeHandler = (
  event: IpcMainInvokeEvent,
  ...args: unknown[]
) => unknown | Promise<unknown>;

export type SendListener = (event: IpcMainEvent, ...args: unknown[]) => void;

export type RegisteredIpcChannels = {
  invoke: ReadonlyArray<ValidInvokeChannel>;
  send: ReadonlyArray<ValidSendChannel>;
};

export type IpcRegistrar = {
  /**
   * invoke (ipcRenderer.invoke) 用の handler を登録する。
   */
  handle: (channel: ValidInvokeChannel, handler: InvokeHandler) => void;
  /**
   * send (ipcRenderer.send) 用の listener を登録する。
   */
  on: (channel: ValidSendChannel, listener: SendListener) => void;
  /**
   * 登録済みチャンネル一覧を返す。
   */
  getRegistered: () => RegisteredIpcChannels;
  /**
   * 解除（best-effort）。
   */
  dispose: () => void;
};

/**
 * `ipcMain` をラップして「登録したもの」を追跡する registrar を作る。
 */
export function createIpcRegistrar(
  ipcMain: IpcMainLike,
  security: { authorize: (channel: IpcChannel, event: IpcSenderEvent) => IpcWindowRole }
): IpcRegistrar {
  const invoke = new Set<ValidInvokeChannel>();
  const send = new Set<ValidSendChannel>();
  const sendListeners = new Map<ValidSendChannel, SendListener>();

  const handle: IpcRegistrar['handle'] = (channel, handler) => {
    if (invoke.has(channel)) {
      throw new Error(`IPC invoke handler is already registered: ${channel}`);
    }
    invoke.add(channel);
    ipcMain.handle(channel, (event, ...args) => {
      security.authorize(channel, event);
      return handler(event, ...args);
    });
  };

  const on: IpcRegistrar['on'] = (channel, listener) => {
    if (send.has(channel)) {
      // 既存実装は基本 1 チャンネル 1 リスナー前提。誤って重複登録すると leak/多重実行になる。
      throw new Error(`IPC send listener is already registered: ${channel}`);
    }
    send.add(channel);
    const guardedListener: SendListener = (event, ...args) => {
      try {
        security.authorize(channel, event);
      } catch (error) {
        if (error instanceof IpcSenderRejectedError) return;
        throw error;
      }
      listener(event, ...args);
    };
    sendListeners.set(channel, guardedListener);
    ipcMain.on(channel, guardedListener);
  };

  const getRegistered: IpcRegistrar['getRegistered'] = () => ({
    invoke: Array.from(invoke),
    send: Array.from(send),
  });

  const dispose: IpcRegistrar['dispose'] = () => {
    // NOTE:
    // - 実運用では dispose を使うケースは少ないが、テストや将来の multi-window 再初期化で役立つ。
    for (const ch of invoke) {
      try {
        ipcMain.removeHandler(ch);
      } catch {
        // best-effort
      }
    }
    for (const [ch, listener] of sendListeners.entries()) {
      try {
        ipcMain.removeListener(ch, listener);
      } catch {
        // best-effort
      }
    }
  };

  return { handle, on, getRegistered, dispose };
}
