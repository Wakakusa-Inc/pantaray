import type React from 'react';

/** ラベル列と操作列の 1 行。囲まずに、列の揃いだけで関係を示す。 */
export function AiConnectionRow({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor?: string;
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <div className="ai-row">
      {htmlFor ? (
        <label className="ai-row-label" htmlFor={htmlFor}>
          {label}
        </label>
      ) : (
        <span className="ai-row-label">{label}</span>
      )}
      <div className="ai-row-control">{children}</div>
    </div>
  );
}
