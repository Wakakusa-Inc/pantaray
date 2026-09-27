export const SYSTEM_CAPTURE_EXCLUDED_OWNER_NAMES = [
  'Spotlight',
  'Notification Center',
  'Control Center',
] as const;

const SYSTEM_CAPTURE_EXCLUDED_OWNER_NAME_SET = new Set(
  SYSTEM_CAPTURE_EXCLUDED_OWNER_NAMES.map((ownerName) => ownerName.toLowerCase())
);

export function isSystemCaptureExcludedOwnerName(ownerName: string | null | undefined): boolean {
  const normalized = String(ownerName || '')
    .trim()
    .toLowerCase();
  return normalized.length > 0 && SYSTEM_CAPTURE_EXCLUDED_OWNER_NAME_SET.has(normalized);
}
