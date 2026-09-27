/**
 * Renderer-ready application icons.
 *
 * The bundle's own `.icns` is the only source that distinguishes one app from
 * another (see `appBundleIcon`); `app.getFileIcon` stays as the platform's answer
 * for a bundle that ships no readable icon resource, and a bundle neither can
 * describe falls through to the picker's neutral placeholder.
 */

import { app, nativeImage } from 'electron';

import { readAppBundleIconPng } from './appBundleIcon';

/** Rendered width in pixels: sharp at the 18 px rows on any display scale factor. */
const ICON_RENDER_WIDTH = 64;

/** A bundle's icon does not change while the app stays installed. */
const iconDataUrlByBundlePath = new Map<string, string | null>();

function renderBundleIcon(bundlePath: string): string | null {
  const png = readAppBundleIconPng(bundlePath);
  if (!png) return null;
  const image = nativeImage.createFromBuffer(png);
  if (image.isEmpty()) return null;
  return image
    .resize({ width: ICON_RENDER_WIDTH, height: ICON_RENDER_WIDTH, quality: 'best' })
    .toDataURL();
}

async function readFileIcon(bundlePath: string): Promise<string | null> {
  try {
    return (await app.getFileIcon(bundlePath, { size: 'normal' })).toDataURL();
  } catch (error) {
    console.error(`Failed to read the file icon for ${bundlePath}:`, error);
    return null;
  }
}

/** PNG data URL of an application's icon, or null when neither source answers. */
export async function readAppIconDataUrl(bundlePath: string): Promise<string | null> {
  const cached = iconDataUrlByBundlePath.get(bundlePath);
  if (cached !== undefined) return cached;
  const iconDataUrl = renderBundleIcon(bundlePath) ?? (await readFileIcon(bundlePath));
  iconDataUrlByBundlePath.set(bundlePath, iconDataUrl);
  return iconDataUrl;
}
