const assert = require('assert');
const { test } = require('node:test');

process.env.PANTARAY_LOG_LEVEL = 'silent';
process.env.PANTARAY_LOG_SALT = 'test-log-salt';
process.env.FRONTEND_PORT = '3001';

const { OutboundEvent } = require('../shared/events');
const { WS_CLOSE_CODE_UNAUTHORIZED, WS_CLOSE_CODE_FORBIDDEN } = require('../shared/ws_close_codes');
const { createOrchestrationWS } = require('../electron/ws_orchestration');
const {
  WS_CLOSE_CODE_BAD_GATEWAY,
  WS_CLOSE_CODE_GOING_AWAY,
  WS_CLOSE_CODE_TRY_AGAIN_LATER,
} = require('../electron/ws_reconnect_policy');
const {
  createFakeTimers,
  createFakeWebSocketClass,
  parseSentMessages,
} = require('./helpers/electron_ws_fakes');

/** @typedef {{ status: string, error?: string, code?: number, httpStatus?: number, httpStatusMessage?: string }} WsStatusPayload */

function buildClient({ FakeWebSocket, timers, forwardStatusToRenderers = () => {} }) {
  return createOrchestrationWS({
    forwardEventToRenderers: () => {},
    forwardStatusToRenderers,
    showNotification: () => {},
    WebSocketImpl: FakeWebSocket,
    timers,
    now: () => 1000,
  });
}

test('WS: connects with the runtime opaque token and skips a missing credential', () => {
  // The local runtime issues `secrets.token_urlsafe(32)`, which has none of a
  // JWT's segments; rejecting it here silently disables orchestration.
  for (const headers of [
    { Authorization: 'Bearer 7Qd-lS9xaB1cJk0zPmR4tVwXyZ2nHgE5uI8oL3rT6vY' },
    { Authorization: 'Bearer local-api-token' },
  ]) {
    const { FakeWebSocket, instances } = createFakeWebSocketClass({ withPing: false });
    const client = buildClient({ FakeWebSocket, timers: createFakeTimers() });
    client.connect('ws://example.test/ws', headers);
    assert.equal(instances.length, 1);
  }

  for (const headers of [{}, { Authorization: '' }, { Authorization: 'Bearer   ' }]) {
    const { FakeWebSocket, instances } = createFakeWebSocketClass({ withPing: false });
    const client = buildClient({ FakeWebSocket, timers: createFakeTimers() });
    client.connect('ws://example.test/ws', headers);
    assert.equal(instances.length, 0);
  }
});

test('WS: manual reconnect immediately creates one authenticated socket and ignores stale events', () => {
  const timers = createFakeTimers();
  const { FakeWebSocket, instances } = createFakeWebSocketClass({ withPing: false });
  const events = [];
  const statuses = [];
  const client = createOrchestrationWS({
    WebSocketImpl: FakeWebSocket, timers, now: () => 1000,
    showNotification: () => {},
    forwardEventToRenderers: event => events.push(event),
    forwardStatusToRenderers: status => statuses.push(status),
  });
  client.connect('ws://example.test/owner-a', { Authorization: 'Bearer token-a' });
  const oldSocket = instances[0];
  client.send({ event: 'old-owner-command' });
  client.disconnect();
  client.connect('ws://example.test/owner-b', { Authorization: 'Bearer token-b' });
  client.connect('ws://example.test/owner-b', { Authorization: 'Bearer token-b' });
  assert.equal(instances.length, 2);
  assert.equal(instances[1].url, 'ws://example.test/owner-b');
  assert.equal(instances[1].options.headers.Authorization, 'Bearer token-b');
  oldSocket.emit('open');
  oldSocket.emit('message', JSON.stringify({ event: OutboundEvent.SESSION_STARTED, data: { session_id: 'old-session' } }));
  oldSocket.emit('close', 1006, 'late');
  assert.deepEqual(events, []);
  assert.deepEqual(statuses, [{ status: 'closed' }]);
  const replacement = instances[1];
  replacement.readyState = FakeWebSocket.OPEN;
  replacement.emit('open');
  client.connect('ws://example.test/owner-b', { Authorization: 'Bearer token-b' });
  assert.equal(instances.length, 2);
  assert.deepEqual(parseSentMessages(replacement), []);
  client.send({ event: 'new-owner-command' });
  assert.deepEqual(parseSentMessages(replacement), [{ event: 'new-owner-command' }]);
});

test('WS: manual disconnect waits for the new session before resuming another owner process', () => {
  const timers = createFakeTimers();
  const { FakeWebSocket, instances } = createFakeWebSocketClass({ withPing: false });
  let now = 1000;
  const statuses = [];
  const client = createOrchestrationWS({
    WebSocketImpl: FakeWebSocket, timers, now: () => now,
    showNotification: () => {},
    forwardEventToRenderers: () => {},
    forwardStatusToRenderers: status => statuses.push(status),
  });
  client.connect('ws://example.test/owner-a', { Authorization: 'Bearer token-a' });
  instances[0].readyState = FakeWebSocket.OPEN;
  instances[0].emit('open');
  instances[0].emit('message', JSON.stringify({ event: OutboundEvent.SESSION_STARTED, data: { session_id: 'session-a' } }));
  instances[0].emit('message', JSON.stringify({ event: OutboundEvent.PROCESS_STARTED,
    meta: { kind: 'action', process_id: 'process-a', action_id: 'action-a', suggestion_id: 'suggestion-a', command_id: 'command-a' },
    data: { kind: 'action', process_id: 'process-a', action_id: 'action-a', suggestion_id: 'suggestion-a',
      command_id: 'command-a', accepted_at: '2026-09-17T00:00:00Z', started_at: '2026-09-17T00:00:01Z' } }));
  client.disconnect();
  now = 2000;
  client.connect('ws://example.test/owner-b', { Authorization: 'Bearer token-b' });
  const replacement = instances[1];
  replacement.readyState = FakeWebSocket.OPEN;
  replacement.emit('open');
  assert.equal(client.resumeProcess({ kind: 'action', processId: 'process-b', actionId: 'action-b' }), false);
  assert.deepEqual(parseSentMessages(replacement), []);
  replacement.emit('message', JSON.stringify({ event: OutboundEvent.SESSION_STARTED, data: { session_id: 'session-b' } }));
  assert.deepEqual(statuses.findLast(status => status.status === 'session_started'), {
    status: 'session_started', session_id: 'session-b', previous_session_id: null,
  });
  const resumes = parseSentMessages(replacement).filter(message => message.event === 'resume_session');
  assert.equal(resumes.length, 1);
  assert.equal(resumes[0].data.session_id, 'session-b');
  assert.equal(resumes[0].data.process_id, 'process-b');
});

test('WS: close(4401/4403) stops reconnect scheduling', () => {
  for (const code of [WS_CLOSE_CODE_UNAUTHORIZED, WS_CLOSE_CODE_FORBIDDEN]) {
    const timers = createFakeTimers();
    const { FakeWebSocket, instances } = createFakeWebSocketClass({ withPing: false });
    const client = buildClient({ FakeWebSocket, timers });

    client.connect('ws://example.test/ws', { Authorization: 'Bearer local-api-token' });
    const ws = instances[0];
    ws.readyState = FakeWebSocket.OPEN;
    ws.emit('open');
    ws.emit('close', code, 'auth rejected');

    assert.equal(timers.timeouts.length, 0);
  }
});

test('WS: transport error schedules reconnect', async () => {
  const timers = createFakeTimers();
  const { FakeWebSocket, instances } = createFakeWebSocketClass({ withPing: false });
  /** @type {WsStatusPayload[]} */
  const statuses = [];
  const client = buildClient({
    FakeWebSocket,
    timers,
    forwardStatusToRenderers: (status) => {
      statuses.push(status);
    },
  });

  client.connect('ws://example.test/ws', { Authorization: 'Bearer local-api-token' });
  instances[0].emit('error', new Error('temporary DNS failure'));

  assert.equal(timers.timeouts.length, 1);
  assert.deepEqual(statuses.at(-1), { status: 'error', error: 'temporary DNS failure' });

  await timers.runNextTimeout();

  assert.equal(instances.length, 2);
  assert.equal(instances[1].url, 'ws://example.test/ws');
});

test('WS: non-retryable close after socket error cancels reconnect', () => {
  const timers = createFakeTimers();
  const { FakeWebSocket, instances } = createFakeWebSocketClass({ withPing: false });
  const client = buildClient({ FakeWebSocket, timers });

  client.connect('ws://example.test/ws', { Authorization: 'Bearer local-api-token' });
  const ws = instances[0];
  ws.emit('error', new Error('transport before policy close'));

  assert.equal(timers.timeouts.length, 1);

  ws.emit('close', WS_CLOSE_CODE_UNAUTHORIZED, 'auth rejected');

  assert.equal(timers.timeouts.length, 0);
});

test('WS: socket error buffers sends until replacement opens', async () => {
  const timers = createFakeTimers();
  const { FakeWebSocket, instances } = createFakeWebSocketClass({ withPing: false });
  const client = buildClient({ FakeWebSocket, timers });

  client.connect('ws://example.test/ws', { Authorization: 'Bearer local-api-token' });
  const oldSocket = instances[0];
  oldSocket.readyState = FakeWebSocket.OPEN;
  oldSocket.emit('open');
  oldSocket.emit('error', new Error('transport failed after open'));

  client.send({ event: 'test_event', data: { ok: true } });

  assert.equal(oldSocket.sent.length, 0);
  assert.equal(timers.timeouts.length, 1);

  await timers.runNextTimeout();
  const replacementSocket = instances[1];
  replacementSocket.readyState = FakeWebSocket.OPEN;
  replacementSocket.emit('open');

  assert.equal(replacementSocket.sent.length, 1);
});

test('WS: retryable close(1013) schedules reconnect', async () => {
  const timers = createFakeTimers();
  const { FakeWebSocket, instances } = createFakeWebSocketClass({ withPing: false });
  const client = buildClient({ FakeWebSocket, timers });

  client.connect('ws://example.test/ws', { Authorization: 'Bearer local-api-token' });
  const ws = instances[0];
  ws.readyState = FakeWebSocket.OPEN;
  ws.emit('open');
  ws.emit('close', WS_CLOSE_CODE_TRY_AGAIN_LATER, 'auth_service_unavailable');

  assert.equal(timers.timeouts.length, 1);
  await timers.runNextTimeout();

  assert.equal(instances.length, 2);
  assert.equal(instances[1].url, 'ws://example.test/ws');
});

test('WS: server drain and gateway close codes schedule reconnect', async () => {
  for (const code of [WS_CLOSE_CODE_GOING_AWAY, WS_CLOSE_CODE_BAD_GATEWAY]) {
    const timers = createFakeTimers();
    const { FakeWebSocket, instances } = createFakeWebSocketClass({ withPing: false });
    const client = buildClient({ FakeWebSocket, timers });

    client.connect('ws://example.test/ws', { Authorization: 'Bearer local-api-token' });
    const ws = instances[0];
    ws.readyState = FakeWebSocket.OPEN;
    ws.emit('open');
    ws.emit('close', code, 'server draining');

    assert.equal(timers.timeouts.length, 1);
    await timers.runNextTimeout();
    assert.equal(instances.length, 2);
    assert.equal(instances[1].url, 'ws://example.test/ws');
  }
});

test('WS: stale close from previous socket does not clear active connection', async () => {
  const timers = createFakeTimers();
  const { FakeWebSocket, instances } = createFakeWebSocketClass({ withPing: false });
  const client = buildClient({ FakeWebSocket, timers });

  client.connect('ws://example.test/ws', { Authorization: 'Bearer local-api-token' });
  const oldSocket = instances[0];
  oldSocket.emit('error', new Error('temporary network failure'));
  await timers.runNextTimeout();

  const activeSocket = instances[1];
  activeSocket.readyState = FakeWebSocket.OPEN;
  activeSocket.emit('open');
  activeSocket.emit(
    'message',
    JSON.stringify({ event: OutboundEvent.SESSION_STARTED, data: { session_id: 'S2' } })
  );

  oldSocket.emit('close', 1006, 'late close from old socket');
  activeSocket.emit(
    'message',
    JSON.stringify({
      event: OutboundEvent.ERROR,
      event_id: 'E-active',
      meta: { process_id: 'P-active' },
      data: { error_type: 'transient', error_code: 'X' },
    })
  );

  const sent = parseSentMessages(activeSocket);
  const ack = sent.find((m) => m && m.event === 'ack_event' && m.data?.event_id === 'E-active');
  assert.ok(ack, 'active socket should still send ack after stale close');
});

test('WS: retryable unexpected-response schedules reconnect', async () => {
  const timers = createFakeTimers();
  const { FakeWebSocket, instances } = createFakeWebSocketClass({ withPing: false });
  /** @type {WsStatusPayload[]} */
  const statuses = [];
  let responseResumed = false;
  let requestAborted = false;
  let socketDestroyed = false;
  const client = buildClient({
    FakeWebSocket,
    timers,
    forwardStatusToRenderers: (status) => {
      statuses.push(status);
    },
  });

  client.connect('ws://example.test/ws', { Authorization: 'Bearer local-api-token' });
  instances[0].emit(
    'unexpected-response',
    {
      abort: () => {
        requestAborted = true;
      },
      socket: {
        destroyed: false,
        destroy: () => {
          socketDestroyed = true;
        },
      },
    },
    {
      statusCode: 503,
      statusMessage: 'Service Unavailable',
      resume: () => {
        responseResumed = true;
      },
    }
  );

  assert.equal(responseResumed, true);
  assert.equal(requestAborted, true);
  assert.equal(socketDestroyed, true);
  assert.deepEqual(statuses.at(-2), {
    status: 'unexpected_response',
    httpStatus: 503,
    httpStatusMessage: 'Service Unavailable',
  });
  assert.deepEqual(statuses.at(-1), { status: 'closed' });
  assert.equal(timers.timeouts.length, 1);

  await timers.runNextTimeout();
  assert.equal(instances.length, 2);
});

test('WS: unauthorized unexpected-response does not reconnect', () => {
  const timers = createFakeTimers();
  const { FakeWebSocket, instances } = createFakeWebSocketClass({ withPing: false });
  /** @type {WsStatusPayload[]} */
  const statuses = [];
  let requestAborted = false;
  let socketDestroyed = false;
  const client = buildClient({
    FakeWebSocket,
    timers,
    forwardStatusToRenderers: (status) => {
      statuses.push(status);
    },
  });

  client.connect('ws://example.test/ws', { Authorization: 'Bearer local-api-token' });
  instances[0].emit(
    'unexpected-response',
    {
      abort: () => {
        requestAborted = true;
      },
      socket: {
        destroyed: false,
        destroy: () => {
          socketDestroyed = true;
        },
      },
    },
    {
      statusCode: 401,
      statusMessage: 'Unauthorized',
      resume: () => {},
    }
  );

  assert.equal(requestAborted, true);
  assert.equal(socketDestroyed, true);
  assert.deepEqual(statuses.at(-2), {
    status: 'unexpected_response',
    httpStatus: 401,
    httpStatusMessage: 'Unauthorized',
  });
  assert.deepEqual(statuses.at(-1), { status: 'closed' });
  assert.equal(timers.timeouts.length, 0);
});
