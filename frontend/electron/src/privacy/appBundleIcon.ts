/**
 * Application icons read from the bundle's own icon resource.
 *
 * `app.getFileIcon` cannot tell two applications apart on this platform: it answers
 * with one byte-identical generic placeholder for every `.app` bundle — verified on
 * macOS 26 with Electron 41 for Chrome, Notion, Slack, LINE, Chatwork, Pantaray and
 * Calculator, all of which returned the same 1181-byte PNG. The icon the Finder
 * shows lives in the bundle instead: `CFBundleIconFile` names an `.icns` under
 * `Contents/Resources`, and every `.icns` written this decade stores its large
 * variants as PNG, so the real icon is one plist lookup and a walk over the icns
 * element table away — no image decoder and no dependency.
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

/** Signature (8) + IHDR length (4) + `IHDR` (4); the width is the next big-endian u32. */
const PNG_IHDR_WIDTH_OFFSET = 16;

/** Shortest PNG header a width can be read from: through the IHDR width and height. */
const PNG_HEADER_BYTES = 24;

/** `icns` magic (4) + file length (4); elements start after it. */
const ICNS_HEADER_BYTES = 8;

/** Element type (4) + element length (4), the length counting this header. */
const ICNS_ELEMENT_HEADER_BYTES = 8;

/**
 * Smallest source variant worth taking, in pixels.
 *
 * The picker renders its icons at 64 px, so anything below that would be upscaled;
 * taking twice that keeps the downscale sharp without decoding a 1024 px variant.
 */
const MINIMUM_SOURCE_WIDTH = 128;

type IcnsImage = { width: number; png: Buffer };

/**
 * PNG variants held by an `.icns`, in file order.
 *
 * The element type says which size a variant is, not how it is encoded: the same
 * `ic09` may hold JPEG 2000 in an old file and PNG in a new one. The payload's own
 * signature is what decides, so a legacy or unknown type is skipped rather than
 * handed to the image decoder as a PNG.
 */
function readIcnsImages(icns: Buffer): IcnsImage[] {
  const images: IcnsImage[] = [];
  if (icns.length < ICNS_HEADER_BYTES || icns.toString('ascii', 0, 4) !== 'icns') return images;
  const end = Math.min(icns.readUInt32BE(4), icns.length);
  let offset = ICNS_HEADER_BYTES;
  while (offset + ICNS_ELEMENT_HEADER_BYTES <= end) {
    const length = icns.readUInt32BE(offset + 4);
    // A length that does not advance past its own header, or runs past the end,
    // means the table is malformed: keep what was read instead of looping forever.
    if (length < ICNS_ELEMENT_HEADER_BYTES || offset + length > end) break;
    const payload = icns.subarray(offset + ICNS_ELEMENT_HEADER_BYTES, offset + length);
    if (payload.length >= PNG_HEADER_BYTES && payload.subarray(0, 8).equals(PNG_SIGNATURE)) {
      images.push({ width: payload.readUInt32BE(PNG_IHDR_WIDTH_OFFSET), png: payload });
    }
    offset += length;
  }
  return images;
}

/**
 * The PNG variant to render from, or null when the file holds none.
 *
 * The smallest variant at or above the render size is preferred over the largest one
 * so a 1024 px artwork is not decoded to draw an 18 px row; a file whose variants are
 * all smaller still yields its best one rather than nothing.
 */
export function selectIcnsPng(icns: Buffer): Buffer | null {
  const images = readIcnsImages(icns);
  if (images.length === 0) return null;
  const usable = images.filter((image) => image.width >= MINIMUM_SOURCE_WIDTH);
  const ordered =
    usable.length > 0
      ? usable.sort((left, right) => left.width - right.width)
      : images.sort((left, right) => right.width - left.width);
  return ordered[0].png;
}

/** `Contents/Resources` name of the bundle icon, with the extension macOS allows omitting. */
function readIconResourceName(bundlePath: string): string | null {
  let value: string;
  try {
    value = execFileSync(
      '/usr/bin/plutil',
      ['-extract', 'CFBundleIconFile', 'raw', '-o', '-', '--', `${bundlePath}/Contents/Info.plist`],
      { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }
    ).trim();
  } catch {
    // A bundle that names no icon file draws its icon from an asset catalog, which
    // needs a decoder this reader deliberately does not own.
    return null;
  }
  if (!value) return null;
  return value.toLowerCase().endsWith('.icns') ? value : `${value}.icns`;
}

/**
 * PNG bytes of an application's own icon, or null when the bundle does not carry one
 * in a form that can be read without an image decoder.
 */
export function readAppBundleIconPng(bundlePath: string): Buffer | null {
  const resourceName = readIconResourceName(bundlePath);
  if (!resourceName) return null;
  let icns: Buffer;
  try {
    icns = fs.readFileSync(path.join(bundlePath, 'Contents/Resources', resourceName));
  } catch {
    // `CFBundleIconFile` naming a resource the bundle does not ship is the app's own
    // packaging mistake, not a condition this reader can act on.
    return null;
  }
  return selectIcnsPng(icns);
}
