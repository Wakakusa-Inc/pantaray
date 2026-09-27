import { MESSAGES } from './messages';

export type UiLanguage = keyof typeof MESSAGES;
export type MessageKey = keyof (typeof MESSAGES)['en'];
