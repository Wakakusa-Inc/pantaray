type MessageMap = Readonly<Record<string, string>>;

type LocalizedMessages<EnglishMessages extends MessageMap> = Readonly<{
  en: EnglishMessages;
  ja: Readonly<{ [Key in keyof EnglishMessages]: string }>;
}>;

export function defineMessages<const EnglishMessages extends MessageMap>(
  messages: LocalizedMessages<EnglishMessages>
): LocalizedMessages<EnglishMessages> {
  return messages;
}
