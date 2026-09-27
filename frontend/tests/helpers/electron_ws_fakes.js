function createFakeTimers() {
  /** @type {Array<{ id: number, ms: number, fn: Function }>} */
  const timeouts = [];
  /** @type {Array<{ id: number, ms: number, fn: Function }>} */
  const intervals = [];
  let nextId = 1;
  return {
    timeouts,
    intervals,
    setTimeout: (fn, ms) => {
      const id = nextId++;
      timeouts.push({ id, ms: Number(ms) || 0, fn });
      return id;
    },
    clearTimeout: (id) => {
      const idx = timeouts.findIndex((t) => t.id === id);
      if (idx >= 0) timeouts.splice(idx, 1);
    },
    setInterval: (fn, ms) => {
      const id = nextId++;
      intervals.push({ id, ms: Number(ms) || 0, fn });
      return id;
    },
    clearInterval: (id) => {
      const idx = intervals.findIndex((t) => t.id === id);
      if (idx >= 0) intervals.splice(idx, 1);
    },
    runNextTimeout: async () => {
      const next = timeouts.shift();
      if (!next) return;
      await next.fn();
    },
  };
}

function createFakeWebSocketClass({ withPing = true } = {}) {
  const instances = [];

  class FakeWebSocket {
    static OPEN = 1;
    static CONNECTING = 0;
    static CLOSED = 3;

    constructor(url, options) {
      this.url = url;
      this.options = options || {};
      this.readyState = FakeWebSocket.CONNECTING;
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
      this.sent.push(String(data));
    }

    ping(data) {
      if (!withPing) {
        throw new Error('ping is disabled for this fake');
      }
      this.pings.push(data);
    }

    close(code, reason) {
      this.closeCalls.push({ code, reason });
      this.readyState = FakeWebSocket.CLOSED;
    }
  }

  return { FakeWebSocket, instances };
}

function parseSentMessages(ws) {
  return ws.sent
    .map((s) => {
      try {
        return JSON.parse(s);
      } catch {
        return null;
      }
    })
    .filter(Boolean);
}

module.exports = {
  createFakeTimers,
  createFakeWebSocketClass,
  parseSentMessages,
};
