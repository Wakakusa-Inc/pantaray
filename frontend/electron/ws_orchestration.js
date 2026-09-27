const DefaultWebSocket = require('ws');
const { InboundEvent, OutboundEvent } = require('../shared/events');
const { createLogger } = require('./logger');
const { buildWebSocketOptions } = require('./ws_connection_options');
const { closeFailedHandshake } = require('./ws_failed_handshake');
const { createProcessResumeState } = require('./ws_orchestration_process_state');
const { RECONNECT_INITIAL_DELAY_MS, nextReconnectDelayMs, shouldReconnectAfterCloseCode, shouldReconnectAfterHttpStatus } = require('./ws_reconnect_policy');
const logger = createLogger();
const {
  WS_CLOSE_CODE_UNAUTHORIZED, // 4401: 認証エラー（Unauthorized / Authentication required）
  WS_CLOSE_CODE_FORBIDDEN,    // 4403: 権限エラー（Forbidden / Permission denied）
} = require('../shared/ws_close_codes');

function createOrchestrationWS({
  showNotification,
  forwardEventToRenderers,
  forwardStatusToRenderers,
  // DI for tests
  WebSocketImpl = DefaultWebSocket,
  timers = {},
  now = () => Date.now(),
}) {
  const WS = WebSocketImpl || DefaultWebSocket;
  const WS_OPEN = typeof WS.OPEN === 'number' ? WS.OPEN : 1;
  const setTimeoutFn = timers.setTimeout || setTimeout;
  const clearTimeoutFn = timers.clearTimeout || clearTimeout;
  const setIntervalFn = timers.setInterval || setInterval;
  const clearIntervalFn = timers.clearInterval || clearInterval;
  const nowFn = typeof now === 'function' ? now : () => Date.now();

  let ws = null;
  let wsUrl = null;
  let wsHeaders = {};
  let shouldReconnect = false;
  let reconnectDelayMs = RECONNECT_INITIAL_DELAY_MS;
  let reconnectTimerId = null;
  let pendingMessages = [];
  let lastSuggestionId = null;
  let lastProcessId = null;
  let currentPhase = null; // 'suggestion' | 'action' | null
  let currentSessionId = null; // 最新のサーバーセッションID
  let connState = 'disconnected'; // 'disconnected' | 'connecting' | 'connected'
  const resolvedHeartbeatInterval = Number(process.env.WS_HEARTBEAT_INTERVAL_MS ?? 30000);
  const HEARTBEAT_INTERVAL_MS = Number.isFinite(resolvedHeartbeatInterval) && resolvedHeartbeatInterval > 0
    ? resolvedHeartbeatInterval
    : 30000;
  const resolvedHeartbeatTimeout = Number(process.env.WS_HEARTBEAT_TIMEOUT_MS ?? 10000);
  const HEARTBEAT_TIMEOUT_MS = Number.isFinite(resolvedHeartbeatTimeout) && resolvedHeartbeatTimeout > 0
    ? resolvedHeartbeatTimeout
    : 10000;
  let heartbeatIntervalId = null;
  let heartbeatTimeoutId = null;
  let lastPingSentAtMs = null;

  function clearReconnectTimer() {
    if (reconnectTimerId === null) return;
    clearTimeoutFn(reconnectTimerId);
    reconnectTimerId = null;
  }

  function scheduleReconnect() {
    if (!shouldReconnect || reconnectTimerId !== null) return;
    const delay = reconnectDelayMs;
    reconnectDelayMs = nextReconnectDelayMs(reconnectDelayMs);
    reconnectTimerId = setTimeoutFn(() => {
      reconnectTimerId = null;
      if (shouldReconnect) {
        open();
      }
    }, delay);
  }

  function isCurrentSocket(socket) {
    return socket && ws === socket;
  }

  function clearHeartbeatTimers() {
    if (heartbeatIntervalId) {
      clearIntervalFn(heartbeatIntervalId);
      heartbeatIntervalId = null;
    }
    if (heartbeatTimeoutId) {
      clearTimeoutFn(heartbeatTimeoutId);
      heartbeatTimeoutId = null;
    }
    lastPingSentAtMs = null;
  }

  function startHeartbeat(socket) {
    if (!socket || typeof socket.ping !== 'function') return;
    clearHeartbeatTimers();

    const sendPing = () => {
      if (!socket || socket.readyState !== WS_OPEN) return;
      lastPingSentAtMs = nowFn();
      logger.debug('WS_HEARTBEAT_PING', {
        corr: { ws_session_id: currentSessionId, process_id: lastProcessId },
        at: new Date(lastPingSentAtMs).toISOString(),
      });
      try {
        socket.ping('heartbeat');
      } catch (err) {
        logger.warn('WS_HEARTBEAT_PING_ERR', { ok: false, err });
        return;
      }
      if (heartbeatTimeoutId) {
        clearTimeoutFn(heartbeatTimeoutId);
      }
      heartbeatTimeoutId = setTimeoutFn(() => {
        try {
          console.warn('WS heartbeat timeout detected', {
            sessionId: currentSessionId,
            processId: lastProcessId,
            lastPingAt: lastPingSentAtMs,
          });
        } catch (_) {
          // noop
        }
        try {
          socket.close(4001, 'heartbeat timeout');
        } catch (_) {
          // noop
        }
      }, HEARTBEAT_TIMEOUT_MS);
    };

    heartbeatIntervalId = setIntervalFn(sendPing, HEARTBEAT_INTERVAL_MS);
    sendPing();
  }

  function sendAckForEvent(eventId, processId) {
    if (!eventId || !processId || !currentSessionId) return;
    sendRaw({
      event: InboundEvent.ACK_EVENT,
      data: {
        session_id: currentSessionId,
        process_id: processId,
        event_id: eventId,
      },
    });
  }

  function sendRaw(payload, { throwOnError = false } = {}) {
    try {
      if (connState === 'connected' && ws && ws.readyState === WS_OPEN) {
        ws.send(typeof payload === 'string' ? payload : JSON.stringify(payload));
      } else {
        pendingMessages.push(typeof payload === 'string' ? payload : JSON.stringify(payload));
      }
    } catch (e) {
      logger.warn('WS_SEND_ERR', { ok: false, err: e });
      if (throwOnError) {
        throw e;
      }
    }
  }

  const processResumeState = createProcessResumeState({
    sendRaw,
    forwardStatusToRenderers,
    showNotification,
    getCurrentSessionId: () => currentSessionId,
  });

  function connect(url, headers = {}) {
    if (!url) return;
    // Require a bearer credential so the handshake is not closed for missing auth.
    // The local runtime issues an opaque token, so presence is all this boundary
    // can assert: the credential's shape belongs to whoever minted it.
    const auth = headers && headers.Authorization;
    const token = typeof auth === 'string' ? auth.replace(/^\s*Bearer\s+/i, '').trim() : '';
    if (!token) {
      logger.warn('WS_CONNECT_SKIP', { ok: false, reason: 'missing_authorization' });
      return;
    }
    if (connState === 'connecting' || connState === 'connected') return; // single-connection guard
    wsUrl = url;
    wsHeaders = headers || {};
    shouldReconnect = true;
    open();
  }

  function disconnect() {
    shouldReconnect = false;
    clearReconnectTimer();
    pendingMessages = [];
    logger.info('WS_DISCONNECT_REQUEST', {
      ok: true,
      corr: { ws_session_id: currentSessionId, suggestion_id: lastSuggestionId, process_id: lastProcessId },
    });
    const closingSocket = ws;
    ws = null;
    wsUrl = null;
    wsHeaders = {};
    connState = 'disconnected';
    currentSessionId = null;
    lastSuggestionId = null;
    lastProcessId = null;
    currentPhase = null;
    processResumeState.clearRegistries({ force: true });
    clearHeartbeatTimers();
    try {
      closingSocket?.close(1000, 'manual disconnect');
    } catch {
      logger.warn('WS_DISCONNECT_ERR', { ok: false });
    }
    if (closingSocket) forwardStatusToRenderers?.({ status: 'closed' });
  }

  function open() {
    if (!wsUrl) return;
    if (connState === 'connecting' || (connState === 'connected' && ws && ws.readyState === WS_OPEN)) return;
    try {
      connState = 'connecting';
      const attemptUrl = wsUrl;
      logger.info('WS_CONNECT_ATTEMPT', {
        ok: true,
        ws: { url: attemptUrl },
      });
      const socket = new WS(attemptUrl, buildWebSocketOptions(wsHeaders));
      ws = socket;

      socket.on('open', () => {
        if (!isCurrentSocket(socket)) return;
        reconnectDelayMs = RECONNECT_INITIAL_DELAY_MS;
        clearReconnectTimer();
        connState = 'connected';
        logger.info('WS_CONNECTED', {
          ok: true,
          ws: { url: attemptUrl },
          corr: { ws_session_id: currentSessionId, suggestion_id: lastSuggestionId, process_id: lastProcessId },
        });
        forwardStatusToRenderers && forwardStatusToRenderers({ status: 'connected' });
        if (pendingMessages.length > 0) {
          const queuedMessages = pendingMessages;
          pendingMessages = [];
          let sentCount = 0;
          try {
            for (const queued of queuedMessages) {
              socket.send(queued);
              sentCount += 1;
            }
          } catch (e) {
            pendingMessages = queuedMessages.slice(sentCount);
            logger.warn('WS_FLUSH_ERR', { ok: false, err: e });
          }
        }
        startHeartbeat(socket);
      });

      socket.on('message', (data) => {
        if (!isCurrentSocket(socket)) return;
        try {
          const msg = JSON.parse(String(data));
          const event = msg?.event;
          const eventId = msg?.event_id || null;
          const processId = msg?.meta?.process_id || msg?.data?.process_id || null;
          const suggestionId = msg?.meta?.suggestion_id || msg?.data?.suggestion_id || null;
          const actionId = msg?.meta?.action_id || msg?.data?.action_id || null;
          const commandId = msg?.meta?.command_id || msg?.data?.command_id || null;
          const physicalRunOnly = event === OutboundEvent.PROCESS_COMPLETED && msg?.data?.physical_run_only === true;
          // 受信イベントのサマリのみログ（payload全文は出さない）
          const dataObj = msg && typeof msg.data === 'object' && msg.data ? msg.data : {};
          const dataKeys = Object.keys(dataObj).slice(0, 20);
          logger.debug('WS_RX', {
            ok: true,
            kind: event || null,
            corr: { event_id: eventId, ws_session_id: currentSessionId, process_id: processId, suggestion_id: suggestionId, action_id: actionId, command_id: commandId },
            data_keys: dataKeys,
          });

          switch (event) {
            case OutboundEvent.SESSION_STARTED: {
              const previousSessionId = currentSessionId;
              currentSessionId = msg?.data?.session_id || null;
              // サーバ側セッション確立。レンダラへ通知（遅延開始のトリガーに使用）
              try {
                forwardStatusToRenderers && forwardStatusToRenderers({ status: 'session_started', session_id: currentSessionId, previous_session_id: previousSessionId });
              } catch (_) {
                // no-op
              }
              processResumeState.flushPendingResumeRequests();
              processResumeState.resumePendingProcesses();
              break;
            }
            case OutboundEvent.ERROR: {
              try {
                const err = msg?.data || {};
                logger.warn('WS_RX_ERROR', {
                  ok: false,
                  corr: { event_id: eventId, ws_session_id: currentSessionId, process_id: processId, suggestion_id: suggestionId, action_id: actionId },
                  err: {
                    error_type: err?.error_type || null,
                    error_code: err?.error_code || null,
                    error_message: err?.error_message || null,
                  },
                });
                const type = String(err?.error_type || '').toLowerCase();
                if (type === 'authentication_error') {
                  // 認証エラー時は再接続しない
                  shouldReconnect = false;
                  try { if (ws) ws.close(); } catch {}
                }
              } catch (e) {
                // no-op
              }
              sendAckForEvent(eventId, processId);
              break;
            }
            case OutboundEvent.PROCESS_STARTED: {
              const sid = suggestionId || null;
              const processKind = (msg?.data && msg.data.kind) || ((msg?.data && (msg.data.action_id || msg.data.accepted_at)) ? 'action' : 'suggestion');
              const isActionStart = processKind === 'action';
              processResumeState.markProcessStarted({
                processId,
                suggestionId: sid,
                actionId: msg?.data?.action_id || null,
                commandId: msg?.data?.command_id || msg?.meta?.command_id || null,
                kind: processKind,
                eventId,
              });
              if (sid) {
                lastSuggestionId = String(sid);
              }
              lastProcessId = processId || lastProcessId;
              currentPhase = processKind;
              sendAckForEvent(eventId, processId);
              break;
            }
            case OutboundEvent.ACTION_STEP:
            case OutboundEvent.PROCESS_PAUSED: {
              processResumeState.markProcessEvent(processId, eventId);
              sendAckForEvent(eventId, processId);
              break;
            }
            case OutboundEvent.PROCESS_COMPLETED: {
              processResumeState.markProcessCompleted(processId, eventId);
              lastProcessId = processId || lastProcessId;
              if (suggestionId) lastSuggestionId = suggestionId;
              if (suggestionId) {
                processResumeState.hideSuggestionOverlay(suggestionId);
              }
              processResumeState.removeProcessState(processId);
              sendAckForEvent(eventId, processId);
              break;
            }
            case OutboundEvent.SUGGESTION_REACTION_COMMITTED: {
              processResumeState.markProcessEvent(processId, eventId);
              const reaction = String(msg?.data?.reaction || '').toLowerCase();
              if (reaction === 'rejected' && suggestionId) {
                processResumeState.hideSuggestionOverlay(suggestionId);
              }
              sendAckForEvent(eventId, processId);
              break;
            }
            case OutboundEvent.SUGGESTION_CHUNK:
            case OutboundEvent.COMPLETION_CHUNK: {
              const resolvedKind = (msg && msg.meta && msg.meta.kind)
                || (msg?.event === OutboundEvent.SUGGESTION_CHUNK ? 'suggestion' : currentPhase)
                || 'suggestion';
              msg.meta = msg.meta || {};
              msg.meta.kind = resolvedKind;
              processResumeState.markProcessChunk(processId, eventId);
              processResumeState.maybeShowOverlayForSuggestion(suggestionId, msg?.data?.content);
              sendAckForEvent(eventId, processId);
              break;
            }
            case OutboundEvent.SESSION_RESUMED: {
              try {
                console.info('WS session resumed', {
                  sessionId: currentSessionId,
                  processId,
                  resumedFrom: msg?.data?.resumed_from_chunk,
                  missing: Array.isArray(msg?.data?.missing_chunks) ? msg.data.missing_chunks.length : undefined,
                });
              } catch (_) {
                // noop
              }
              processResumeState.flushPendingResumeRequests();
              try {
                forwardStatusToRenderers && forwardStatusToRenderers({
                  status: 'session_resumed',
                  process_id: processId,
                  resumed_from: msg?.data?.resumed_from_chunk,
                  missing: Array.isArray(msg?.data?.missing_chunks) ? msg.data.missing_chunks.length : 0,
                });
              } catch (_) {
                // noop
              }
              sendAckForEvent(eventId, processId);
              break;
            }
            case OutboundEvent.SESSION_EXPIRED: {
              try {
                console.warn('WS session expired', {
                  sessionId: currentSessionId,
                  reason: msg?.data?.reason,
                  processId,
                });
              } catch (_) {
                // noop
              }
              sendAckForEvent(eventId, processId);
              break;
            }
            default:
              break;
          }

          if (!physicalRunOnly) forwardEventToRenderers && forwardEventToRenderers(msg);
        } catch (e) {
          console.error('WS message parse error:', e);
        }
      });

      socket.on('pong', () => {
        if (!isCurrentSocket(socket)) return;
        if (heartbeatTimeoutId) {
          clearTimeoutFn(heartbeatTimeoutId);
          heartbeatTimeoutId = null;
        }
        const rttMs = lastPingSentAtMs ? nowFn() - lastPingSentAtMs : null;
        try {
          console.info('WS heartbeat pong', {
            sessionId: currentSessionId,
            processId: lastProcessId,
            roundTripMs: rttMs,
          });
        } catch (_) {
          // noop
        }
      });

        socket.on('unexpected-response', (req, res) => {
          if (!isCurrentSocket(socket)) return;
          try {
            const status = res && res.statusCode;
            const statusMessage = res && res.statusMessage;
            console.error('WS unexpected-response:', status, statusMessage);
            forwardStatusToRenderers && forwardStatusToRenderers({ status: 'unexpected_response', httpStatus: status, httpStatusMessage: statusMessage });
            const cleanup = closeFailedHandshake(req, res);
            if (cleanup.errors.length > 0) {
              logger.warn('WS_UNEXPECTED_RESPONSE_CLEANUP_ERR', {
                ok: false,
                errors: cleanup.errors,
              });
            }
            clearHeartbeatTimers();
            ws = null;
            connState = 'disconnected';
            processResumeState.flagRunningProcessesForResume(currentSessionId);
            currentSessionId = null;
            processResumeState.clearRegistries({ force: false });
            forwardStatusToRenderers && forwardStatusToRenderers({ status: 'closed' });
            if (shouldReconnectAfterHttpStatus(status)) {
              scheduleReconnect();
            } else {
              shouldReconnect = false;
              clearReconnectTimer();
            }
          } catch (e) {
            console.error('WS unexpected-response handler error:', e);
          }
        });

        socket.on('close', (code, reason) => {
          if (!isCurrentSocket(socket)) return;
          clearHeartbeatTimers();
          const reasonText = Buffer.isBuffer(reason) ? reason.toString() : (reason || '');
          const wasClean = typeof socket.wasClean === 'boolean' ? socket.wasClean : undefined;
          try {
            console.warn('WS close', {
              code,
              reason: reasonText,
              wasClean,
              sessionId: currentSessionId,
              processId: lastProcessId,
            });
          } catch (_) {
            // noop
          }
          forwardStatusToRenderers && forwardStatusToRenderers({ status: 'closed', code });
          ws = null;
          connState = 'disconnected';
          processResumeState.flagRunningProcessesForResume(currentSessionId);
          currentSessionId = null;
          processResumeState.clearRegistries({ force: false });
          const nonRetryableCloseCodes = new Set([
            WS_CLOSE_CODE_UNAUTHORIZED,
            WS_CLOSE_CODE_FORBIDDEN,
          ]);
          if (shouldReconnectAfterCloseCode(code, nonRetryableCloseCodes)) {
            scheduleReconnect();
          } else {
            shouldReconnect = false;
            clearReconnectTimer();
          }
        });

        socket.on('error', (err) => {
          if (!isCurrentSocket(socket)) return;
          console.error('WS error:', err?.message || err);
          connState = 'disconnected';
          processResumeState.flagRunningProcessesForResume(currentSessionId);
          forwardStatusToRenderers && forwardStatusToRenderers({ status: 'error', error: String(err?.message || err) });
          clearHeartbeatTimers();
          scheduleReconnect();
        });
    } catch (e) {
      logger.warn('WS_CONNECT_ERR', { ok: false, err: e });
      console.error('WS connect error:', e);
      connState = 'disconnected';
      scheduleReconnect();
    }
  }

  function resumeProcess(args = {}) {
    const success = processResumeState.performResume(args);
    if (!success) {
      processResumeState.enqueueResumeRequest(args);
    }
    return success;
  }

  return {
    connect,
    disconnect,
    send: (message) => sendRaw(message, { throwOnError: true }),
    resumeProcess,
  };
}

module.exports = { createOrchestrationWS };
