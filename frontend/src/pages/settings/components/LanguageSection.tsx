import React, { useEffect, useRef, useState } from 'react';

import type { Translate } from '../types';

interface LanguageSectionProps {
  language: 'en' | 'ja';
  setLanguage: (language: 'en' | 'ja') => Promise<void> | void;
  t: Translate;
}

export function LanguageSection({
  language,
  setLanguage,
  t,
}: LanguageSectionProps): React.JSX.Element {
  const [isOpen, setIsOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    const handlePointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('pointerdown', handlePointerDown);
    return () => document.removeEventListener('pointerdown', handlePointerDown);
  }, [isOpen]);

  return (
    <div className="dashboard-section">
      <div className="settings-language-row">
        <h3 className="dashboard-section-title" style={{ margin: 0 }}>
          {t('settings.language.title')}
        </h3>
        <div className="settings-select" ref={menuRef}>
          <button
            type="button"
            className="settings-select-button"
            aria-haspopup="listbox"
            aria-expanded={isOpen}
            aria-label={t('settings.language.title')}
            onClick={() => setIsOpen((current) => !current)}
          >
            {t(`settings.language.option.${language}`)}
            <span className="settings-select-chevron" aria-hidden="true" />
          </button>
          {isOpen ? (
            <div className="settings-select-menu" role="listbox">
              {(['en', 'ja'] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  role="option"
                  aria-selected={language === value}
                  className={[
                    'settings-select-option',
                    language === value ? 'settings-select-option--selected' : null,
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  onClick={() => {
                    void setLanguage(value);
                    setIsOpen(false);
                  }}
                >
                  {t(`settings.language.option.${value}`)}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
