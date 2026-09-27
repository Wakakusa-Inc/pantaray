const RECONNECT_INITIAL_DELAY_MS = 1000;
const RECONNECT_MAX_DELAY_MS = 16000;

const WS_CLOSE_CODE_GOING_AWAY = 1001;
const WS_CLOSE_CODE_ABNORMAL = 1006;
const WS_CLOSE_CODE_INTERNAL_ERROR = 1011;
const WS_CLOSE_CODE_SERVICE_RESTART = 1012;
const WS_CLOSE_CODE_TRY_AGAIN_LATER = 1013;
const WS_CLOSE_CODE_BAD_GATEWAY = 1014;
const WS_CLOSE_CODE_HEARTBEAT_TIMEOUT = 4001;

const RETRYABLE_CLOSE_CODES = new Set([
  WS_CLOSE_CODE_GOING_AWAY,
  WS_CLOSE_CODE_ABNORMAL,
  WS_CLOSE_CODE_INTERNAL_ERROR,
  WS_CLOSE_CODE_SERVICE_RESTART,
  WS_CLOSE_CODE_TRY_AGAIN_LATER,
  WS_CLOSE_CODE_BAD_GATEWAY,
  WS_CLOSE_CODE_HEARTBEAT_TIMEOUT,
]);

function shouldReconnectAfterCloseCode(code, nonRetryableCloseCodes) {
  if (nonRetryableCloseCodes.has(code)) return false;
  return RETRYABLE_CLOSE_CODES.has(code);
}

function shouldReconnectAfterHttpStatus(status) {
  if (typeof status !== 'number') return false;
  if (status === 408 || status === 429) return true;
  return status >= 500 && status <= 599;
}

function nextReconnectDelayMs(currentDelayMs) {
  return Math.min(currentDelayMs * 2, RECONNECT_MAX_DELAY_MS);
}

module.exports = {
  RECONNECT_INITIAL_DELAY_MS,
  WS_CLOSE_CODE_BAD_GATEWAY,
  WS_CLOSE_CODE_GOING_AWAY,
  WS_CLOSE_CODE_TRY_AGAIN_LATER,
  shouldReconnectAfterCloseCode,
  shouldReconnectAfterHttpStatus,
  nextReconnectDelayMs,
};
