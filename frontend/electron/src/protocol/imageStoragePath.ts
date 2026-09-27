/**
 * User-scoped image `storage_path` rules (TypeScript port).
 *
 * The canonical rules live in `agents/src/pantaray_agents/security/storage_paths.py`
 * (`_is_valid_user_image_storage_path`) and the allowed extension/MIME table lives in
 * `agents/src/pantaray_agents/security/image_media_types.py`. The renderer never sees an
 * absolute path, so Electron main has to decide by itself whether a `storage_path` may be
 * written or served; that decision must not be laxer than the Python reader's.
 *
 * `tests/electron_image_storage_path.test.js` runs the same case table as
 * `agents/tests/unit/security/test_storage_paths.py`.
 *
 * The one deliberate difference: Python's `UUID()` also accepts non-canonical spellings
 * (no hyphens, braces, `urn:uuid:`). Here only the canonical 8-4-4-4-12 form is accepted,
 * which is what `crypto.randomUUID()` produces. Stricter is safe: a path this module
 * rejects is simply never written and never served.
 */

export const ACTION_IMAGE_MIME_TYPES = [
  'image/gif',
  'image/jpeg',
  'image/png',
  'image/webp',
] as const;

export type ActionImageMimeType = (typeof ACTION_IMAGE_MIME_TYPES)[number];

export const IMAGE_MIME_TYPE_BY_EXTENSION: Readonly<Record<string, ActionImageMimeType>> = {
  '.gif': 'image/gif',
  '.jpeg': 'image/jpeg',
  '.jpg': 'image/jpeg',
  '.png': 'image/png',
  '.webp': 'image/webp',
};

export const IMAGE_EXTENSION_BY_MIME_TYPE: Readonly<Record<ActionImageMimeType, string>> = {
  'image/gif': '.gif',
  'image/jpeg': '.jpeg',
  'image/png': '.png',
  'image/webp': '.webp',
};

/** `AGENT_SCREENCAPTURE_STORAGE_PATH_MAX_LEN` (local backend runtime bundle). */
export const IMAGE_STORAGE_PATH_MAX_LENGTH = 512;

/** Artifact-root-relative directory that holds every user-scoped image. */
export const GENERATED_IMAGES_DIRECTORY_SEGMENTS = ['generated', 'images'] as const;

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const CANONICAL_UUID_PATTERN =
  /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
const FORBIDDEN_CHARACTERS = ['\n', '\r', '\t', '\0', '\\'];

function isRealIsoDate(value: string): boolean {
  if (!DATE_PATTERN.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00.000Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().startsWith(value);
}

/** UTC calendar day used as the middle `storage_path` segment. */
export function imageStorageDateSegment(now: Date): string {
  return now.toISOString().slice(0, 10);
}

export function isValidImageStoragePath(params: {
  userId: string;
  storagePath: string;
  maxLength?: number;
}): boolean {
  const userId = params.userId.trim();
  if (userId === '') return false;

  const storagePath = params.storagePath.trim();
  if (storagePath === '') return false;
  if (storagePath.length > (params.maxLength ?? IMAGE_STORAGE_PATH_MAX_LENGTH)) return false;
  if (FORBIDDEN_CHARACTERS.some((character) => storagePath.includes(character))) return false;
  if (storagePath.includes('..')) return false;

  const prefix = `${userId}/`;
  if (!storagePath.startsWith(prefix)) return false;
  const parts = storagePath.slice(prefix.length).split('/');
  if (parts.length !== 2) return false;

  const [dateSegment, filename] = parts;
  if (!isRealIsoDate(dateSegment)) return false;

  const extensionIndex = filename.lastIndexOf('.');
  if (extensionIndex <= 0) return false;
  if (!(filename.slice(extensionIndex).toLowerCase() in IMAGE_MIME_TYPE_BY_EXTENSION)) return false;
  return CANONICAL_UUID_PATTERN.test(filename.slice(0, extensionIndex));
}

/** MIME type implied by a `storage_path` extension, or null when it is not an image path. */
export function imageMimeTypeForStoragePath(storagePath: string): ActionImageMimeType | null {
  const extensionIndex = storagePath.lastIndexOf('.');
  if (extensionIndex <= 0) return null;
  return IMAGE_MIME_TYPE_BY_EXTENSION[storagePath.slice(extensionIndex).toLowerCase()] ?? null;
}

function startsWithBytes(bytes: Uint8Array, signature: readonly number[], offset = 0): boolean {
  if (bytes.length < offset + signature.length) return false;
  return signature.every((byte, index) => bytes[offset + index] === byte);
}

/**
 * MIME type implied by the leading bytes, or null when the content is not an allowed image.
 *
 * A declared MIME type or a file extension is caller-supplied metadata; only the bytes decide
 * what is written to disk and what `Content-Type` is served.
 */
export function sniffImageMimeType(bytes: Uint8Array): ActionImageMimeType | null {
  if (startsWithBytes(bytes, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) return 'image/png';
  if (startsWithBytes(bytes, [0xff, 0xd8, 0xff])) return 'image/jpeg';
  if (startsWithBytes(bytes, [0x47, 0x49, 0x46, 0x38])) return 'image/gif';
  if (
    startsWithBytes(bytes, [0x52, 0x49, 0x46, 0x46]) &&
    startsWithBytes(bytes, [0x57, 0x45, 0x42, 0x50], 8)
  ) {
    return 'image/webp';
  }
  return null;
}

/** Privileged scheme that serves stored images to the renderer. */
export const ACTION_IMAGE_SCHEME = 'pantaray-image';
/** `standard: true` schemes require a host; the path carries the whole `storage_path`. */
export const ACTION_IMAGE_URL_HOST = 'local';

/** Renderer-facing URL for a stored image. The renderer never learns the absolute path. */
export function buildActionImageUrl(storagePath: string): string {
  const encoded = storagePath.split('/').map(encodeURIComponent).join('/');
  return `${ACTION_IMAGE_SCHEME}://${ACTION_IMAGE_URL_HOST}/${encoded}`;
}
