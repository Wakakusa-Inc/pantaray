import { useEffect, useRef, useState } from 'react';
import type { Translate } from '../types';
import { AiConnectionRow } from './AiConnectionRow';

export function AiConnectionModelRow({
  model,
  candidates,
  selectionOnly = false,
  onSave,
  t,
}: {
  model: string;
  candidates: readonly string[];
  selectionOnly?: boolean;
  onSave: (model: string) => Promise<void>;
  t: Translate;
}) {
  const selectedModel = selectionOnly && !candidates.includes(model) ? '' : model;
  const [draft, setDraft] = useState(selectedModel);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const selectRef = useRef<HTMLSelectElement>(null);
  useEffect(() => {
    setDraft(selectedModel);
  }, [selectedModel]);
  useEffect(() => {
    if (failed && !saving) (selectionOnly ? selectRef : inputRef).current?.focus();
  }, [failed, saving, selectionOnly]);

  const save = async () => {
    if (selectionOnly && !candidates.includes(draft)) return;
    setSaving(true);
    setFailed(false);
    try {
      await onSave(draft.trim());
    } catch {
      // Main may persist the model before runtime apply fails; the same value still needs a retry.
      setFailed(true);
    } finally {
      setSaving(false);
    }
  };

  return (
    <AiConnectionRow label={t('settings.aiConnection.modelLabel')} htmlFor="ai-model">
      <form
        className="ai-inline"
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        {selectionOnly ? (
          <select
            id="ai-model"
            ref={selectRef}
            className="history-filter-select"
            value={draft}
            disabled={saving}
            onChange={(event) => setDraft(event.target.value)}
          >
            <option value="" disabled>
              {t('settings.aiConnection.modelSelectPlaceholder')}
            </option>
            {candidates.map((candidate) => (
              <option key={candidate} value={candidate}>
                {candidate}
              </option>
            ))}
          </select>
        ) : (
          <input
            id="ai-model"
            ref={inputRef}
            className="history-filter-input"
            type="text"
            spellCheck={false}
            list={candidates.length > 0 ? 'ai-model-candidates' : undefined}
            placeholder={t('settings.aiConnection.modelPlaceholder')}
            value={draft}
            disabled={saving}
            onChange={(event) => setDraft(event.target.value)}
          />
        )}
        <button
          type="submit"
          className="settings-action-button"
          disabled={
            saving ||
            (selectionOnly && !candidates.includes(draft)) ||
            (!failed && draft.trim() === model)
          }
        >
          {t('settings.aiConnection.model.save')}
        </button>
      </form>
      {!selectionOnly && candidates.length > 0 ? (
        <datalist id="ai-model-candidates">
          {candidates.map((candidate) => (
            <option key={candidate} value={candidate} />
          ))}
        </datalist>
      ) : null}
      <p className="ai-note ai-note--control">
        {t(
          selectionOnly
            ? 'settings.aiConnection.chatgptModelHint'
            : 'settings.aiConnection.modelHint'
        )}
      </p>
      <p className="ai-check ai-check--failed" role="status">
        {failed ? t('settings.aiConnection.model.saveFailed') : ''}
      </p>
    </AiConnectionRow>
  );
}
