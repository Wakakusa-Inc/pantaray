import type { useI18n } from '@/context/useI18n';

/** `exclude` records everything but the listed items; `include_only` records only them. */
export type CaptureFilterMode = 'exclude' | 'include_only';

export interface CaptureAppEntry {
  name: string;
  bundleId: string | null;
}

export interface CaptureAppFilter {
  mode: CaptureFilterMode;
  entries: CaptureAppEntry[];
}

export interface CaptureWebsiteFilter {
  mode: CaptureFilterMode;
  hosts: string[];
}

/** The part of the recording filter the settings dialog edits. */
export interface CaptureFilter {
  apps: CaptureAppFilter;
  websites: CaptureWebsiteFilter;
}

export interface InstalledApp {
  name: string;
  bundleId: string | null;
  iconDataUrl: string | null;
}

export class UserFacingError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'UserFacingError';
  }
}

export type IdeFileRulesMode = 'off' | 'on';
export type IdeFileNameUnavailablePolicy = 'block' | 'allow';

export interface IdeSensitivePresets {
  blockEnvFiles: boolean;
}

export interface IdeFileRules {
  mode: IdeFileRulesMode;
  onFileNameUnavailable: IdeFileNameUnavailablePolicy;
  sensitivePresets?: IdeSensitivePresets;
}

export type Translate = ReturnType<typeof useI18n>['t'];

export type ElectronCaptureSettings = Parameters<
  NonNullable<NonNullable<Window['electron']>['privacy']>['updateCaptureSettings']
>[0];
