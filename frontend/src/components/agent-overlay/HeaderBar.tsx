// HeaderBar styled-only
import styled from 'styled-components';

const HeaderRow = styled.div`
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 4px;
  padding: 2px 0;
  margin-bottom: 2px;
  -webkit-app-region: no-drag;
  cursor: default;
  touch-action: none;
  position: relative;
  z-index: 1;
  min-height: 16px;
  /* テキスト量が多くてもヘッダーが詰まらないようにする */
  flex-shrink: 0;
`;

export default HeaderRow;

export const HeaderButtonGroup = styled.div`
  display: flex;
  gap: 4px;
  -webkit-app-region: no-drag;
  cursor: default;
  flex-shrink: 0;
`;
