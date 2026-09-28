import { ChangeEvent, FormEvent, useEffect, useState } from 'react';
import { Search } from 'lucide-react';
import { limitHistorySearchText } from '@/hooks/useSuggestionHistory';
import { useI18n } from '@/context/useI18n';

/** Waits for a pause in typing so each keystroke does not start its own history read. */
const SEARCH_DEBOUNCE_MS = 250;

type HistorySearchFieldProps = {
  searchText: string;
  onSearch: (searchText: string) => void;
};

/** Searches as the user types; the native search field clears with its × button or Escape. */
const HistorySearchField = ({ searchText, onSearch }: HistorySearchFieldProps) => {
  const { t } = useI18n();
  const [draft, setDraft] = useState(searchText);

  useEffect(() => {
    if (draft === searchText) return;
    const timer = window.setTimeout(() => onSearch(draft), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [draft, searchText, onSearch]);

  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    setDraft(limitHistorySearchText(event.target.value));
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSearch(draft);
  };

  return (
    <form role="search" onSubmit={handleSubmit} className="history-search">
      <Search size={15} aria-hidden="true" className="history-search__icon" />
      <input
        type="search"
        aria-label={t('history.search')}
        placeholder={t('history.search')}
        value={draft}
        onChange={handleChange}
        className="history-filter-input history-search__input"
      />
    </form>
  );
};

export default HistorySearchField;
