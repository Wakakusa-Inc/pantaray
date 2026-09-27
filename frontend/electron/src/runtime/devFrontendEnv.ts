export function parseFrontendPort(raw: unknown): number {
  const value = String(raw ?? '').trim();
  if (!/^[0-9]{1,5}$/.test(value)) {
    throw new Error('FRONTEND_PORT must be a numeric port (1-65535).');
  }
  const port = Number.parseInt(value, 10);
  if (!Number.isFinite(port) || port < 1 || port > 65535) {
    throw new Error('FRONTEND_PORT must be a numeric port (1-65535).');
  }
  return port;
}

export function requireFrontendPort(env: NodeJS.ProcessEnv = process.env): number {
  const raw = env.FRONTEND_PORT;
  if (typeof raw !== 'string' || raw.trim().length === 0) {
    throw new Error('FRONTEND_PORT is required in development runtime.');
  }
  return parseFrontendPort(raw);
}

export function buildFrontendDevOrigin(env: NodeJS.ProcessEnv = process.env): string {
  const url = new URL('http://localhost/');
  url.port = String(requireFrontendPort(env));
  return url.origin;
}

export function buildFrontendDevPageUrl(
  pathname: string,
  env: NodeJS.ProcessEnv = process.env
): string {
  const url = new URL(buildFrontendDevOrigin(env));
  url.pathname = pathname;
  return url.toString();
}
