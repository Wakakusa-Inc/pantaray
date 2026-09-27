// Footer actions styled-only
import styled from 'styled-components';

export const Footer = styled.div<{ $compact?: boolean }>`
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 8px;
  margin-top: auto;
  padding-top: ${(props) => (props.$compact ? '12px' : '8px')};
  padding-bottom: ${(props) => (props.$compact ? '0px' : '4px')};
  min-height: ${(props) => (props.$compact ? '34px' : '38px')};
  -webkit-app-region: no-drag;
  position: relative;
  z-index: 1;
  /* テキスト量が多くてもフッターが詰まらないようにする */
  flex-shrink: 0;
`;

export const FooterActionGroup = styled.div`
  display: flex;
  gap: 8px;
`;

export default Footer;
