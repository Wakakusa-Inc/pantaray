function parseFrontendPort(raw) {
  const value = String(raw || '').trim();
  if (!/^[0-9]{1,5}$/.test(value)) {
    throw new Error('FRONTEND_PORT must be a numeric port (1-65535).');
  }
  const port = Number.parseInt(value, 10);
  if (!Number.isFinite(port) || port < 1 || port > 65535) {
    throw new Error('FRONTEND_PORT must be a numeric port (1-65535).');
  }
  return port;
}

function requireFrontendPort() {
  const raw = process.env.FRONTEND_PORT;
  if (typeof raw !== 'string' || raw.trim().length === 0) {
    throw new Error('FRONTEND_PORT is required in development runtime.');
  }
  return parseFrontendPort(raw);
}

function buildFrontendDevOrigin() {
  const url = new URL('http://localhost/');
  url.port = String(requireFrontendPort());
  return url.origin;
}

function buildFrontendLoopbackOrigin() {
  const url = new URL('http://127.0.0.1/');
  url.port = String(requireFrontendPort());
  return url.origin;
}

function buildFrontendDevPageUrl(pathname) {
  const url = new URL(buildFrontendDevOrigin());
  url.pathname = pathname;
  return url.toString();
}

function buildFrontendDevHashUrl(hashRoute) {
  return `${buildFrontendDevOrigin()}${hashRoute || ''}`;
}

module.exports = {
  buildFrontendDevHashUrl,
  buildFrontendDevOrigin,
  buildFrontendDevPageUrl,
  buildFrontendLoopbackOrigin,
  parseFrontendPort,
  requireFrontendPort,
};
