// WebSocket Close Codes (application-defined)
// 4401: 認証エラー（Unauthorized / Authentication required）。HTTP 401 に相当。
// 4403: 権限エラー（Forbidden / Permission denied）。HTTP 403 に相当。

const WS_CLOSE_CODE_UNAUTHORIZED = 4401;
const WS_CLOSE_CODE_FORBIDDEN = 4403;

module.exports = {
  WS_CLOSE_CODE_UNAUTHORIZED,
  WS_CLOSE_CODE_FORBIDDEN,
};


