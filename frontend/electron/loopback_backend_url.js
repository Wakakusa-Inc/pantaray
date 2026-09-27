const LOOPBACK_HOSTNAMES = new Set(['127.0.0.1', 'localhost']);

class LoopbackBackendUrlError extends Error {
  constructor(message) {
    super(message);
    this.name = 'LoopbackBackendUrlError';
  }
}

function parseLoopbackBackendUrl(value, fieldName = 'BACKEND_URL') {
  const raw = typeof value === 'string' ? value.trim() : '';
  let url;
  try {
    url = new URL(raw);
  } catch {
    throw new LoopbackBackendUrlError(`${fieldName} must be an absolute URL.`);
  }

  if (url.protocol !== 'http:') {
    throw new LoopbackBackendUrlError(`${fieldName} must use http:.`);
  }
  if (!LOOPBACK_HOSTNAMES.has(url.hostname)) {
    throw new LoopbackBackendUrlError(`${fieldName} must target loopback.`);
  }
  if (!url.port) {
    throw new LoopbackBackendUrlError(`${fieldName} must include an explicit port.`);
  }
  const port = Number.parseInt(url.port, 10);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new LoopbackBackendUrlError(`${fieldName} must include a port between 1 and 65535.`);
  }
  if (url.username || url.password) {
    throw new LoopbackBackendUrlError(`${fieldName} must not contain credentials.`);
  }
  if (url.pathname !== '/' || url.search || url.hash) {
    throw new LoopbackBackendUrlError(`${fieldName} must contain only a loopback origin.`);
  }

  return url;
}

function resolveLoopbackBinding(value, fieldName = 'BACKEND_URL') {
  const url = parseLoopbackBackendUrl(value, fieldName);
  const port = Number.parseInt(url.port, 10);
  return {
    appPort: port,
    bindHost: url.hostname === 'localhost' ? '127.0.0.1' : url.hostname,
    bindPort: port,
  };
}

module.exports = {
  LoopbackBackendUrlError,
  parseLoopbackBackendUrl,
  resolveLoopbackBinding,
};
