const { buildFrontendLoopbackOrigin } = require('./dev_frontend_env');

function isPackagedRuntime() {
  const raw = String(process.env.PANTARAY_PACKAGED || '').trim().toLowerCase();
  return raw === '1' || raw === 'true';
}

function buildWebSocketOptions(headers) {
  const options = {
    headers: headers || {},
    perMessageDeflate: false,
    handshakeTimeout: 8000,
  };
  if (!isPackagedRuntime()) {
    options.origin = buildFrontendLoopbackOrigin();
  }
  return options;
}

module.exports = { buildWebSocketOptions };
