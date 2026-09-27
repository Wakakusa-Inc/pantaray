import styled from 'styled-components';
import { COLORS } from './Styled';

export const ActionButton = styled.button<{ $isBusy?: boolean; $visible?: boolean }>`
  position: relative;
  padding: 4px 12px;
  border-radius: 6px;
  font-family: var(--font-sans);
  font-size: var(--text-ui-size-sm);
  font-weight: var(--weight-semibold);
  border: none;
  cursor: pointer;
  overflow: hidden;
  opacity: ${(props) => (props.$visible ? 1 : 0)};
  transition: ${COLORS.reducedMotion
    ? `opacity 0.6s cubic-bezier(0.25, 0.1, 0.25, 1),
     background-color 0.3s cubic-bezier(0.25, 0.1, 0.25, 1),
     border-color 0.3s cubic-bezier(0.25, 0.1, 0.25, 1),
     filter 0.3s ease`
    : `opacity 0.6s cubic-bezier(0.25, 0.1, 0.25, 1),
     background-color 0.3s cubic-bezier(0.25, 0.1, 0.25, 1),
     border-color 0.3s cubic-bezier(0.25, 0.1, 0.25, 1),
     color 0.15s ease,
     transform 0.1s cubic-bezier(0.4, 0, 0.2, 1),
     box-shadow 0.15s ease,
     filter 0.3s ease`};
  -webkit-app-region: no-drag;
  &::before {
    content: '';
    position: absolute;
    inset: 0;
    border-radius: inherit;
    background: radial-gradient(circle, rgba(255, 255, 255, 0.4) 0%, transparent 70%);
    opacity: 0;
    transform: scale(0);
    transition: ${COLORS.reducedMotion ? 'none' : 'opacity 0.2s ease, transform 0.2s ease'};
    pointer-events: none;
  }
  &:hover:not([disabled]) {
    transform: ${COLORS.reducedMotion ? 'none' : 'scale(1.02)'};
  }
  &:active:not([disabled]) {
    transform: ${COLORS.reducedMotion ? 'none' : 'scale(0.98)'};
    &::before {
      opacity: ${COLORS.reducedMotion ? '0' : '1'};
      transform: ${COLORS.reducedMotion ? 'scale(0)' : 'scale(1)'};
    }
  }
  &:focus-visible {
    outline: 2px solid rgba(255, 255, 255, 0.7);
    outline-offset: 2px;
  }
  ${({ $isBusy }) =>
    $isBusy && `opacity: 0.6; cursor: not-allowed; pointer-events: none; filter: saturate(0.7);`}
`;

export const AcceptButton = styled(ActionButton)`
  color: #ffffff;
  font-weight: 700;
  background-color: rgba(45, 80, 140, 0.96);
  border: 1px solid rgba(255, 255, 255, 0.1);
  will-change: background-color, border-color;
  transition:
    opacity 0.6s cubic-bezier(0.25, 0.1, 0.25, 1),
    background-color 0.3s cubic-bezier(0.25, 0.1, 0.25, 1),
    border-color 0.3s cubic-bezier(0.25, 0.1, 0.25, 1),
    color 0.15s ease,
    transform 0.1s cubic-bezier(0.4, 0, 0.2, 1),
    box-shadow 0.15s ease;
  &:hover:not([disabled]) {
    ${({ $isBusy }) =>
      !$isBusy &&
      `background-color: rgba(60, 100, 170, 0.98); border-color: rgba(255, 255, 255, 0.18);`}
  }
  &:active:not([disabled]) {
    background-color: rgba(35, 65, 115, 0.96);
  }
`;

export const RejectButton = styled(ActionButton)`
  background-color: rgba(255, 255, 255, 0.12);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.92);
  font-weight: 700;
  transition:
    opacity 0.6s cubic-bezier(0.25, 0.1, 0.25, 1),
    background-color 0.3s cubic-bezier(0.25, 0.1, 0.25, 1),
    border-color 0.3s cubic-bezier(0.25, 0.1, 0.25, 1),
    color 0.15s ease,
    transform 0.1s cubic-bezier(0.4, 0, 0.2, 1),
    box-shadow 0.15s ease;
  &:hover:not([disabled]) {
    ${({ $isBusy }) =>
      !$isBusy &&
      `background-color: rgba(255, 255, 255, 0.16); border-color: rgba(255, 255, 255, 0.10); color: rgba(255, 255, 255, 0.96);`}
  }
  &:active:not([disabled]) {
    background-color: rgba(255, 255, 255, 0.08);
  }
`;
