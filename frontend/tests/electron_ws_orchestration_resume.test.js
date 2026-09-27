const assert = require('assert');
const { test } = require('node:test');

// テスト中のログノイズを抑える（TAP出力を汚さない）
process.env.PANTARAY_LOG_LEVEL = 'silent';
process.env.PANTARAY_LOG_SALT = 'test-log-salt';
process.env.FRONTEND_PORT = '3001';

const { OutboundEvent } = require('../shared/events');
const { createOrchestrationWS } = require('../electron/ws_orchestration');
const {
  createFakeTimers,
  createFakeWebSocketClass,
  parseSentMessages,
} = require('./helpers/electron_ws_fakes');

/** @typedef {{ event?: string, data?: { summary?: string } }} WsForwardedEvent */

test('WS: packaged runtime does not require FRONTEND_PORT for connection options', () => {
  const previousPackaged = process.env.PANTARAY_PACKAGED;
  const previousFrontendPort = process.env.FRONTEND_PORT;
  try {
    process.env.PANTARAY_PACKAGED = '1';
    delete process.env.FRONTEND_PORT;

    const timers = createFakeTimers();
    const { FakeWebSocket, instances } = createFakeWebSocketClass({ withPing: false });
    const client = createOrchestrationWS({
      forwardEventToRenderers: () => {},
      forwardStatusToRenderers: () => {},
      showNotification: () => {},
        WebSocketImpl: FakeWebSocket,
      timers,
      now: () => 1000,
    });

    client.connect('ws://example.test/ws', { Authorization: 'Bearer local-api-token' });

    assert.equal(instances.length, 1);
    assert.equal(instances[0].options.origin, undefined);
    assert.equal(instances[0].options.headers.Authorization, 'Bearer local-api-token');
  } finally {
    if (previousPackaged === undefined) {
      delete process.env.PANTARAY_PACKAGED;
    } else {
      process.env.PANTARAY_PACKAGED = previousPackaged;
    }
    if (previousFrontendPort === undefined) {
      delete process.env.FRONTEND_PORT;
    } else {
      process.env.FRONTEND_PORT = previousFrontendPort;
    }
  }
});

test('WS: development runtime sends loopback Origin from FRONTEND_PORT', () => {
  const previousPackaged = process.env.PANTARAY_PACKAGED;
  const previousFrontendPort = process.env.FRONTEND_PORT;
  try {
    delete process.env.PANTARAY_PACKAGED;
    process.env.FRONTEND_PORT = '3001';

    const timers = createFakeTimers();
    const { FakeWebSocket, instances } = createFakeWebSocketClass({ withPing: false });
    const client = createOrchestrationWS({
      forwardEventToRenderers: () => {},
      forwardStatusToRenderers: () => {},
      showNotification: () => {},
        WebSocketImpl: FakeWebSocket,
      timers,
      now: () => 1000,
    });

    client.connect('ws://example.test/ws', { Authorization: 'Bearer local-api-token' });

    assert.equal(instances.length, 1);
    assert.equal(instances[0].options.origin, 'http://127.0.0.1:3001');
  } finally {
    if (previousPackaged === undefined) {
      delete process.env.PANTARAY_PACKAGED;
    } else {
      process.env.PANTARAY_PACKAGED = previousPackaged;
    }
    if (previousFrontendPort === undefined) {
      delete process.env.FRONTEND_PORT;
    } else {
      process.env.FRONTEND_PORT = previousFrontendPort;
    }
  }
});

test('WS: ack_event is sent for error events when session_id is known', () => {
  const timers = createFakeTimers();
  const { FakeWebSocket, instances } = createFakeWebSocketClass({ withPing: false });

  const client = createOrchestrationWS({
    forwardEventToRenderers: () => {},
    forwardStatusToRenderers: () => {},
    showNotification: () => {},
    WebSocketImpl: FakeWebSocket,
    timers,
    now: () => 1234567890,
  });

  client.connect('ws://example.test/ws', { Authorization: 'Bearer local-api-token' });
  assert.equal(instances.length, 1);
  const ws = instances[0];
  ws.readyState = FakeWebSocket.OPEN;
  ws.emit('open');

  // session_started で currentSessionId を確立
  ws.emit(
    'message',
    JSON.stringify({ event: OutboundEvent.SESSION_STARTED, data: { session_id: 'S1' } })
  );

  ws.emit(
    'message',
    JSON.stringify({
      event: OutboundEvent.ERROR,
      event_id: 'E1',
      meta: { process_id: 'P1' },
      data: { error_type: 'some_error', error_code: 'X', severity: 'error' },
    })
  );

  const sent = parseSentMessages(ws);
  const ack = sent.find((m) => m && m.event === 'ack_event' && m.data && m.data.event_id === 'E1');
  assert.ok(ack, 'ack_event should be emitted');
  assert.equal(ack.data.session_id, 'S1');
  assert.equal(ack.data.process_id, 'P1');
});

test('WS: physical Action run completion は ACK だけ行い UI へ転送しない', () => {
  const timers = createFakeTimers();
  const { FakeWebSocket, instances } = createFakeWebSocketClass({ withPing: false });
  const forwarded = [];
  const client = createOrchestrationWS({
    forwardEventToRenderers: (message) => forwarded.push(message),
    forwardStatusToRenderers: () => {},
    showNotification: () => {},
    WebSocketImpl: FakeWebSocket,
    timers,
    now: () => 1234567890,
  });

  client.connect('ws://example.test/ws', { Authorization: 'Bearer local-api-token' });
  const ws = instances[0];
  ws.readyState = FakeWebSocket.OPEN;
  ws.emit('open');
  ws.emit(
    'message',
    JSON.stringify({ event: OutboundEvent.SESSION_STARTED, data: { session_id: 'S1' } })
  );
  forwarded.length = 0;
  ws.emit(
    'message',
    JSON.stringify({
      event: OutboundEvent.PROCESS_COMPLETED,
      event_id: 'physical-end',
      data: {
        kind: 'action',
        physical_run_only: true,
        process_id: 'P-physical',
        status: 'canceled',
      },
      meta: { kind: 'action' },
    })
  );

  const ack = parseSentMessages(ws).find(
    (message) => message?.event === 'ack_event' && message.data?.event_id === 'physical-end'
  );
  assert.ok(ack);
  assert.equal(ack.data.process_id, 'P-physical');
  assert.deepStrictEqual(forwarded, []);
  assert.equal(client.resumeProcess({ processId: 'P-physical' }), false);
});

test('WS: heartbeat timeout triggers close(4001)', () => {
  process.env.WS_HEARTBEAT_TIMEOUT_MS = '50';
  process.env.WS_HEARTBEAT_INTERVAL_MS = '30';

  const timers = createFakeTimers();
  const { FakeWebSocket, instances } = createFakeWebSocketClass({ withPing: true });

  const client = createOrchestrationWS({
    forwardEventToRenderers: () => {},
    forwardStatusToRenderers: () => {},
    showNotification: () => {},
    WebSocketImpl: FakeWebSocket,
    timers,
    now: (() => {
      let t = 1000;
      return () => (t += 10);
    })(),
  });

  client.connect('ws://example.test/ws', { Authorization: 'Bearer local-api-token' });
  const ws = instances[0];
  ws.readyState = FakeWebSocket.OPEN;
  ws.emit('open');

  assert.ok(ws.pings.length >= 1, 'ping should be sent on open');
  assert.ok(timers.timeouts.length >= 1, 'heartbeat timeout should be scheduled');

  const lastTimeout = timers.timeouts[timers.timeouts.length - 1];
  lastTimeout.fn();

  assert.ok(ws.closeCalls.length >= 1, 'socket.close should be called on timeout');
  const lastClose = ws.closeCalls[ws.closeCalls.length - 1];
  assert.equal(lastClose.code, 4001);
});

test('WS: resume_session last_cursor rules (suggestion vs action)', () => {
  const timers = createFakeTimers();
  const { FakeWebSocket, instances } = createFakeWebSocketClass({ withPing: false });

  let client;
  client = createOrchestrationWS({
    forwardEventToRenderers: (event) => {
      if (event.event === OutboundEvent.PROCESS_PAUSED) client.resumeProcess({ processId: 'P_a' });
    },
    forwardStatusToRenderers: () => {},
    showNotification: () => {},
    WebSocketImpl: FakeWebSocket,
    timers,
    now: () => 1000,
  });

  client.connect('ws://example.test/ws', { Authorization: 'Bearer local-api-token' });
  const ws = instances[0];
  ws.readyState = FakeWebSocket.OPEN;
  ws.emit('open');

  ws.emit(
    'message',
    JSON.stringify({ event: OutboundEvent.SESSION_STARTED, data: { session_id: 'S1' } })
  );

  // Suggestion process: last_cursor はそのまま使う
  ws.emit(
    'message',
    JSON.stringify({
      event: OutboundEvent.PROCESS_STARTED,
      event_id: 'uuid-start',
      meta: { process_id: 'P_s', suggestion_id: 'Sug1' },
      data: { process_id: 'P_s', suggestion_id: 'Sug1' },
    })
  );
  ws.emit(
    'message',
    JSON.stringify({
      event: OutboundEvent.COMPLETION_CHUNK,
      event_id: 'uuid-chunk-1',
      meta: { process_id: 'P_s', suggestion_id: 'Sug1', kind: 'suggestion' },
      data: { content: 'hello' },
    })
  );

  // Action process: local runtime process event_id をそのまま resume cursor に使う
  ws.emit(
    'message',
    JSON.stringify({
      event: OutboundEvent.PROCESS_STARTED,
      event_id: 'uuid-start-action',
      meta: { process_id: 'P_a', action_id: 'Act1', suggestion_id: 'Sug1' },
      data: { process_id: 'P_a', action_id: 'Act1', suggestion_id: 'Sug1' },
    })
  );
  ws.emit(
    'message',
    JSON.stringify({
      event: OutboundEvent.ACTION_STEP,
      event_id: 'uuid-action-step',
      meta: { process_id: 'P_a', action_id: 'Act1', kind: 'action' },
      data: {
        action_id: 'Act1',
        process_id: 'P_a',
        step_kind: 'tool',
        step_id: 'step-1',
        step_number: 1,
        tool_id: 'read',
        label: 'Read',
        status: 'processing',
        started_at: '2026-03-08T00:00:02Z',
        completed_at: null,
      },
    })
  );
  ws.emit(
    'message',
    JSON.stringify({
      event: OutboundEvent.PROCESS_PAUSED,
      event_id: 'uuid-process-paused',
      meta: { process_id: 'P_a', action_id: 'Act1', kind: 'action' },
      data: {
        kind: 'action',
        process_id: 'P_a',
        action_id: 'Act1',
        reason: 'approval_pending',
      },
    })
  );

  client.resumeProcess({ processId: 'P_s' });

  const sent = parseSentMessages(ws);
  const resumes = sent.filter((m) => m && m.event === 'resume_session');
  assert.ok(resumes.length >= 2);

  const resumeSuggestion = resumes.find((m) => m.data && m.data.process_id === 'P_s');
  assert.ok(resumeSuggestion);
  assert.equal(resumeSuggestion.data.session_id, 'S1');
  assert.equal(resumeSuggestion.data.last_cursor, 'uuid-chunk-1');
  assert.equal(resumeSuggestion.data.last_chunk_index, 0);
  assert.equal(resumeSuggestion.data.kind, 'suggestion');

  const resumeAction = resumes.find((m) => m.data && m.data.process_id === 'P_a');
  assert.ok(resumeAction);
  assert.equal(resumeAction.data.session_id, 'S1');
  assert.equal(resumeAction.data.last_cursor, 'uuid-process-paused');
  assert.equal(resumeAction.data.last_chunk_index, -1);
  assert.equal(resumeAction.data.kind, 'action');
  const pauseAckIndex = sent.findIndex(
    (message) => message?.event === 'ack_event' && message.data?.event_id === 'uuid-process-paused'
  );
  const actionResumeIndex = sent.indexOf(resumeAction);
  assert.ok(pauseAckIndex >= 0 && pauseAckIndex < actionResumeIndex);
});

test('WS: approval resume by action id targets the root process cursor, never a subagent', () => {
  const timers = createFakeTimers();
  const { FakeWebSocket, instances } = createFakeWebSocketClass({ withPing: false });
  let now = 1000;

  const client = createOrchestrationWS({
    forwardEventToRenderers: () => {},
    forwardStatusToRenderers: () => {},
    showNotification: () => {},
    WebSocketImpl: FakeWebSocket,
    timers,
    now: () => now,
  });

  client.connect('ws://example.test/ws', { Authorization: 'Bearer local-api-token' });
  const ws = instances[0];
  ws.readyState = FakeWebSocket.OPEN;
  ws.emit('open');

  ws.emit(
    'message',
    JSON.stringify({ event: OutboundEvent.SESSION_STARTED, data: { session_id: 'S1' } })
  );
  ws.emit(
    'message',
    JSON.stringify({
      event: OutboundEvent.PROCESS_STARTED,
      event_id: 'uuid-start-action',
      meta: { process_id: 'P_root', action_id: 'Act1', suggestion_id: 'Sug1', kind: 'action' },
      data: { process_id: 'P_root', action_id: 'Act1', suggestion_id: 'Sug1' },
    })
  );
  // relay meta は root 固定なので、子 blocker の pause でも cursor は root stream に積まれる。
  ws.emit(
    'message',
    JSON.stringify({
      event: OutboundEvent.PROCESS_PAUSED,
      event_id: 'uuid-subagent-paused',
      meta: { process_id: 'P_root', action_id: 'Act1', kind: 'action' },
      data: {
        kind: 'action',
        process_id: 'P_root',
        action_id: 'Act1',
        reason: 'approval_pending',
      },
    })
  );

  // 承認決定は子 process へ送るが、resume は Action id だけで root transport を解決する。
  assert.equal(client.resumeProcess({ kind: 'action', actionId: 'Act1', fromStart: false }), true);

  const sent = parseSentMessages(ws);
  const resumes = sent.filter((message) => message && message.event === 'resume_session');
  assert.equal(resumes.length, 1);
  assert.equal(resumes[0].data.process_id, 'P_root');
  assert.equal(resumes[0].data.action_id, 'Act1');
  assert.equal(resumes[0].data.last_cursor, 'uuid-subagent-paused');
  assert.equal(resumes[0].data.kind, 'action');

  // token refresh の manual disconnect は registry を消すので actionId だけでは
  // root を解決できない。決定時に控えた root process id が transport を復元する。
  client.disconnect();
  now = 2000;
  client.connect('ws://example.test/ws', { Authorization: 'Bearer local-api-token' });
  const reconnected = instances[1];
  reconnected.readyState = FakeWebSocket.OPEN;
  reconnected.emit('open');
  reconnected.emit(
    'message',
    JSON.stringify({ event: OutboundEvent.SESSION_STARTED, data: { session_id: 'S2' } })
  );

  assert.equal(client.resumeProcess({ kind: 'action', actionId: 'Act1', fromStart: false }), false);
  assert.equal(
    client.resumeProcess({
      kind: 'action',
      processId: 'P_root',
      actionId: 'Act1',
      fromStart: false,
    }),
    true
  );
  const afterReconnect = parseSentMessages(reconnected).filter(
    (message) => message && message.event === 'resume_session'
  );
  assert.equal(afterReconnect.length, 1);
  assert.equal(afterReconnect[0].data.process_id, 'P_root');
  assert.equal(afterReconnect[0].data.session_id, 'S2');
  assert.equal(afterReconnect[0].data.kind, 'action');
});

test('WS: explicit action resume request can attach an unseen approval-resume process', () => {
  const timers = createFakeTimers();
  const { FakeWebSocket, instances } = createFakeWebSocketClass({ withPing: false });

  const client = createOrchestrationWS({
    forwardEventToRenderers: () => {},
    forwardStatusToRenderers: () => {},
    showNotification: () => {},
    WebSocketImpl: FakeWebSocket,
    timers,
    now: () => 1000,
  });

  client.connect('ws://example.test/ws', { Authorization: 'Bearer local-api-token' });
  const ws = instances[0];
  ws.readyState = FakeWebSocket.OPEN;
  ws.emit('open');

  ws.emit(
    'message',
    JSON.stringify({ event: OutboundEvent.SESSION_STARTED, data: { session_id: 'S1' } })
  );

  client.resumeProcess({
    kind: 'action',
    processId: 'P_resume',
    suggestionId: 'Sug1',
    actionId: 'Act1',
    commandId: 'Cmd1',
    fromStart: true,
  });

  const sent = parseSentMessages(ws);
  const resume = sent.find((message) => message && message.event === 'resume_session');
  assert.ok(resume);
  assert.equal(resume.data.process_id, 'P_resume');
  assert.equal(resume.data.kind, 'action');
  assert.equal(resume.data.suggestion_id, 'Sug1');
  assert.equal(resume.data.action_id, 'Act1');
  assert.equal(resume.data.command_id, 'Cmd1');
  assert.equal(resume.data.last_cursor, null);
  assert.equal(resume.data.last_chunk_index, -1);
});

test('WS: manual disconnect discards buffered messages before the next authenticated socket', () => {
  const timers = createFakeTimers();
  const { FakeWebSocket, instances } = createFakeWebSocketClass({ withPing: false });
  let now = 1000;
  const client = createOrchestrationWS({
    forwardEventToRenderers: () => {},
    forwardStatusToRenderers: () => {},
    showNotification: () => {},
    WebSocketImpl: FakeWebSocket,
    timers,
    now: () => now,
  });

  client.connect('ws://example.test/ws', { Authorization: 'Bearer local-api-token' });
  client.send({
    event: 'execute_action',
    data: { suggestion_id: 'Sug1', command_id: 'Cmd1', supplement: 'private condition' },
  });
  client.disconnect();

  now = 2000;
  client.connect('ws://example.test/ws', { Authorization: 'Bearer d.e.f' });
  const replacementSocket = instances[1];
  replacementSocket.readyState = FakeWebSocket.OPEN;
  replacementSocket.emit('open');

  assert.deepEqual(parseSentMessages(replacementSocket), []);
});

test('WS: flush partial failure requeues only unsent messages', async () => {
  const timers = createFakeTimers();
  const instances = [];
  let sendCallCount = 0;

  class PartialFailureWebSocket {
    static OPEN = 1;
    static CONNECTING = 0;
    static CLOSED = 3;

    constructor(url, options) {
      this.url = url;
      this.options = options || {};
      this.readyState = PartialFailureWebSocket.CONNECTING;
      this.sent = [];
      this.pings = [];
      this.closeCalls = [];
      this._handlers = new Map();
      instances.push(this);
    }

    on(event, handler) {
      const list = this._handlers.get(event) || [];
      list.push(handler);
      this._handlers.set(event, list);
    }

    emit(event, ...args) {
      const list = this._handlers.get(event) || [];
      for (const fn of list) fn(...args);
    }

    send(data) {
      sendCallCount += 1;
      if (sendCallCount === 2) {
        throw new Error('flush boom');
      }
      this.sent.push(String(data));
    }

    ping(data) {
      this.pings.push(data);
    }

    close(code, reason) {
      this.closeCalls.push({ code, reason });
      this.readyState = PartialFailureWebSocket.CLOSED;
    }
  }

  const client = createOrchestrationWS({
    forwardEventToRenderers: () => {},
    forwardStatusToRenderers: () => {},
    showNotification: () => {},
    WebSocketImpl: PartialFailureWebSocket,
    timers,
    now: () => 1000,
  });

  client.connect('ws://example.test/ws', { Authorization: 'Bearer local-api-token' });
  assert.equal(instances.length, 1);

  client.send({
    event: 'dismiss_suggestion',
    data: { suggestion_id: 'Sug1' },
  });
  client.send({
    event: 'dismiss_suggestion',
    data: { suggestion_id: 'Sug2' },
  });

  const firstSocket = instances[0];
  firstSocket.readyState = PartialFailureWebSocket.OPEN;
  firstSocket.emit('open');
  assert.equal(parseSentMessages(firstSocket).length, 1);

  firstSocket.emit('close', 1006, 'transport reset');
  await timers.runNextTimeout();

  assert.equal(instances.length, 2);
  const secondSocket = instances[1];
  secondSocket.readyState = PartialFailureWebSocket.OPEN;
  secondSocket.emit('open');

  const resent = parseSentMessages(secondSocket);
  assert.equal(resent.length, 1);
  assert.equal(resent[0]?.data?.suggestion_id, 'Sug2');
});
