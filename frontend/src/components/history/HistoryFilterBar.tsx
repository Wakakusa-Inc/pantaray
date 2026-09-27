import { ChangeEvent, FormEvent, useState } from 'react';
import {
  limitHistorySearchText,
  type SuggestionHistoryFilters,
} from '@/hooks/useSuggestionHistory';
import { useI18n } from '@/context/useI18n';

type HistoryFilterBarProps = {
  filters: SuggestionHistoryFilters;
  onFilterChange: (updater: (prev: SuggestionHistoryFilters) => SuggestionHistoryFilters) => void;
  onReload: () => void;
  disabled?: boolean;
};

/**
 * 提案履歴のフィルターパネル。受け入れステータス、実行ステータス、キーワード検索をまとめて操作できる。
 */
const HistoryFilterBar = ({
  filters,
  onFilterChange,
  onReload,
  disabled = false,
}: HistoryFilterBarProps) => {
  const { t } = useI18n();
  const [localSearch, setLocalSearch] = useState<string>(filters.searchText);

  const statusOptions = [
    { value: 'all', label: t('history.filter.all') },
    { value: 'running', label: t('history.status.running') },
    { value: 'approval_pending', label: t('history.status.approvalPending') },
    { value: 'idle', label: t('history.status.idle') },
  ];

  const handleStatusChange = (event: ChangeEvent<HTMLSelectElement>) => {
    const next = event.target.value;
    onFilterChange((prev) => ({ ...prev, status: next as SuggestionHistoryFilters['status'] }));
  };

  const handleSearchChange = (event: ChangeEvent<HTMLInputElement>) => {
    setLocalSearch(limitHistorySearchText(event.target.value));
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onFilterChange((prev) => ({ ...prev, searchText: localSearch }));
  };

  const handleReset = () => {
    setLocalSearch('');
    onFilterChange(() => ({ status: 'all', searchText: '' }));
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="history-filter-bar"
      aria-label={t('history.filter.ariaLabel')}
      tabIndex={-1}
    >
      <div className="history-filter-row">
        <div className="history-filter-field history-filter-field--search">
          <label className="history-filter-label" htmlFor="history-search">
            {t('history.filter.searchLabel')}
          </label>
          <input
            id="history-search"
            type="search"
            placeholder={t('history.filter.searchPlaceholder')}
            value={localSearch}
            onChange={handleSearchChange}
            className="history-filter-input"
            disabled={disabled}
          />
        </div>

        <div className="history-filter-field history-filter-field--status">
          <label className="history-filter-label" htmlFor="history-status-filter">
            {t('history.filter.statusLabel')}
          </label>
          <select
            id="history-status-filter"
            value={filters.status}
            onChange={handleStatusChange}
            className="history-filter-select"
            disabled={disabled}
          >
            {statusOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        <button type="submit" className="history-filter-button" disabled={disabled}>
          {t('history.filter.searchButton')}
        </button>
      </div>

      <div className="history-filter-actions">
        <button
          type="button"
          onClick={handleReset}
          className="history-filter-link"
          disabled={disabled}
        >
          {t('history.filter.reset')}
        </button>
        <button
          type="button"
          onClick={onReload}
          className="history-filter-link"
          disabled={disabled}
        >
          {t('history.filter.reload')}
        </button>
      </div>
    </form>
  );
};

export default HistoryFilterBar;
