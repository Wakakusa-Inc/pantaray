/**
 * What a browser's active tab URL says about whether that page may be captured.
 *
 * The always-on recorder refuses sign-in and payment pages whatever the user's
 * filter says (`zaneiConfig.ts` writes `block_auth` and `block_payments`, and the
 * recorder decides). The same pages reach a model through `capture_screen`, so the
 * same rule has to hold here - and a rule written twice is a rule that drifts.
 *
 * There is no way to ask the recorder: its policy is a library function with no
 * command that evaluates a URL. So this is the one TypeScript statement of it, and
 * `tests/electron_browser_url_policy.test.js` replays the recorder's own parity
 * cases (`tests/fixtures/zanei_privacy_parity_cases.json`, vendored from the pinned
 * release and re-verified against that tag by `scripts/stage-zanei-runtime.js`)
 * through this module. A recorder release that changes the rule changes those cases,
 * and the test says so.
 *
 * The recorder's vocabulary, kept verbatim: the three places a URL names its own
 * surface - the host's leading label, the path, and the fragment - are each scanned
 * for a whole `/`-separated segment out of one word list, after percent-decoding the
 * unreserved characters and dropping one trailing file extension. Whole segments are
 * what keeps `/blog/login-guide` and `#login-form` capturable. The recorder's flags
 * are not parameters here because nothing in Pantaray turns them off.
 */

/** A page named by its URL, and nothing more of it than the caller may act on. */
export type BrowserUrlDecision =
  | { kind: 'unavailable' }
  | { kind: 'sensitive'; preset: 'authentication' | 'payment' }
  | { kind: 'site'; host: string };

const AUTHENTICATION_SEGMENTS = new Set([
  'login',
  'log-in',
  'signin',
  'sign-in',
  'sign_in',
  'signup',
  'sign-up',
  'sign_up',
  'register',
  'registration',
  'oauth',
  'oauth2',
  'authorize',
  'reset-password',
  'reset_password',
  'password-reset',
  'password_reset',
  'forgot-password',
  'forgot_password',
]);

const PAYMENT_SEGMENTS = new Set([
  'checkout',
  'payment',
  'payments',
  'billing',
  'subscription',
  'subscriptions',
]);

/** Segments that follow a bare `password` segment to name the same route. */
const PASSWORD_FOLLOWERS = new Set(['reset', 'forgot']);

export function decideBrowserUrl(rawUrl: string | null): BrowserUrlDecision {
  const url = parseWebUrl(rawUrl);
  if (url === null) return { kind: 'unavailable' };
  const preset = presetMatch(url);
  return preset === null ? { kind: 'site', host: url.hostname } : { kind: 'sensitive', preset };
}

/**
 * A web page whose URL can be judged at all. Anything else - an unparsable string,
 * `file:`, `data:`, or a browser-internal `chrome://` page - is unavailable rather
 * than a host to filter on: those URLs name no website, and `chrome://settings` is
 * not evidence that the site filter accepts what is on screen.
 */
function parseWebUrl(rawUrl: string | null): URL | null {
  if (rawUrl === null) return null;
  try {
    const url = new URL(rawUrl);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url : null;
  } catch {
    return null;
  }
}

/**
 * An authentication match anywhere in the URL outranks a payment match anywhere.
 *
 * Only the leading host label is read, because that is where a service names itself
 * (`checkout.vendor.test`); a word deeper in the host belongs to the site's own name,
 * so `www.checkout.test` is not matched. A fragment never reaches the server but is
 * visible in the URL bar, and `#/login` cannot be told apart from an in-page anchor
 * from the URL alone, so both are judged as the route they name.
 */
function presetMatch(url: URL): 'authentication' | 'payment' | null {
  const serviceLabel = url.hostname.split('.')[0];
  let payment = false;
  for (const route of [serviceLabel, url.pathname, url.hash.slice(1)]) {
    const matched = scanRoute(route);
    if (matched === 'authentication') return 'authentication';
    if (matched === 'payment') payment = true;
  }
  return payment ? 'payment' : null;
}

function scanRoute(route: string): 'authentication' | 'payment' | null {
  let previous = '';
  let payment = false;
  for (const raw of route.split('/')) {
    const segment = normalizedSegment(raw);
    if (
      AUTHENTICATION_SEGMENTS.has(segment) ||
      (previous === 'password' && PASSWORD_FOLLOWERS.has(segment))
    ) {
      return 'authentication';
    }
    payment ||= PAYMENT_SEGMENTS.has(segment);
    previous = segment;
  }
  return payment ? 'payment' : null;
}

function normalizedSegment(raw: string): string {
  let normalized = '';
  for (let index = 0; index < raw.length; index += 1) {
    const decoded = raw[index] === '%' ? decodeUnreserved(raw.slice(index + 1, index + 3)) : null;
    if (decoded !== null) {
      normalized += decoded;
      index += 2;
      continue;
    }
    normalized += asciiLowercase(raw[index]);
  }
  return withoutOneExtension(normalized);
}

/**
 * One percent-escape, decoded only when it stands for an unreserved character.
 * `%2F` stays written out, so `/guide%2Flogin` is one segment and not two.
 */
function decodeUnreserved(escape: string): string | null {
  if (!/^[0-9a-fA-F]{2}$/.test(escape)) return null;
  const character = String.fromCharCode(Number.parseInt(escape, 16));
  return /^[0-9A-Za-z\-._~]$/.test(character) ? asciiLowercase(character) : null;
}

/**
 * A served page keeps its route in the file name (`login.html`, `signin.php`), so one
 * trailing extension is dropped - bounded in length so a dotted word is not mistaken
 * for a file name.
 */
function withoutOneExtension(segment: string): string {
  const dot = segment.lastIndexOf('.');
  if (dot <= 0) return segment;
  const extension = segment.slice(dot + 1);
  return /^[0-9a-z]{1,10}$/.test(extension) ? segment.slice(0, dot) : segment;
}

/** ASCII-only, matching the recorder: a non-ASCII letter never becomes a listed word. */
function asciiLowercase(value: string): string {
  return value.replace(/[A-Z]/g, (letter) => letter.toLowerCase());
}
