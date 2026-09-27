import styled from 'styled-components';

export const ApprovalDecisionButton = styled.button<{ $variant: 'primary' | 'secondary' }>`
  min-height: 36px;
  padding: 0 14px;
  border-radius: 12px;
  border: 1px solid
    ${({ $variant }) =>
      $variant === 'primary' ? 'rgba(255, 255, 255, 0.18)' : 'rgba(255, 255, 255, 0.12)'};
  background: ${({ $variant }) =>
    $variant === 'primary' ? 'rgba(255, 255, 255, 0.1)' : 'rgba(255, 255, 255, 0.06)'};
  color: rgba(255, 255, 255, 0.92);
  font-family: var(--font-sans);
  font-size: var(--text-ui-size-sm);
  font-weight: var(--weight-semibold);
  cursor: pointer;
  -webkit-app-region: no-drag;

  &:hover:not([disabled]) {
    background: ${({ $variant }) =>
      $variant === 'primary' ? 'rgba(255, 255, 255, 0.14)' : 'rgba(255, 255, 255, 0.1)'};
  }

  &:focus-visible {
    outline: 2px solid rgba(255, 255, 255, 0.7);
    outline-offset: 2px;
  }

  &:disabled {
    cursor: not-allowed;
    opacity: 0.62;
  }
`;
