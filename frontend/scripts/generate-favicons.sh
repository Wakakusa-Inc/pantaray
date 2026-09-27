#!/bin/bash
set -euo pipefail

# Web（Firebase Hosting 等）向けの favicon 一式を生成するスクリプトです。
#
# 目的:
# - 生成物を「内容ハッシュ付きパス」に出力し、CDN/ブラウザの immutable キャッシュ下でも確実に更新できるようにする。
# - Vite の `%BASE_URL%` を使って参照することで、Web（/）と Electron（./）の両方で壊れないようにする。
#
# 生成物:
# - public/favicons/<hash>/
#   - favicon.svg
#   - favicon-16.png
#   - favicon-32.png
#   - apple-touch-icon.png (180x180)
#   - android-chrome-192.png
#   - android-chrome-512.png
#   - site.webmanifest
#
# 依存（必須）:
# - rsvg-convert（SVG→PNG 変換）: macOSなら `brew install librsvg`
# - shasum
#
# 使用法:
#   ./scripts/generate-favicons.sh assets/icons/Pantaray_icon.svg assets/icons/Pantaray_icon_small.svg
#
# 備考:
# - 生成後に `index.html` と `notification.html` の favicon パス（__FAVICON_HASH__）を自動更新します。

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "必要なコマンドが見つかりません: $1" >&2
    exit 2
  fi
}

if [ "${1:-}" = "" ]; then
  echo "使用法: $0 path/to/icon.svg [path/to/icon_small.svg]" >&2
  exit 1
fi

MAIN_SVG="$1"
SMALL_SVG="${2:-}"

case "$MAIN_SVG" in
  *.svg|*.SVG) ;;
  *)
    echo "未対応の拡張子です: $MAIN_SVG（svgのみ対応）" >&2
    exit 3
    ;;
esac

if [ "$SMALL_SVG" != "" ]; then
  case "$SMALL_SVG" in
    *.svg|*.SVG) ;;
    *)
      echo "未対応の拡張子です: $SMALL_SVG（svgのみ対応）" >&2
      exit 3
      ;;
  esac
fi

require_cmd rsvg-convert
require_cmd shasum
require_cmd mkdir
require_cmd cp
require_cmd sed

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

hash_src="$(
  {
    cat "$FRONTEND_DIR/$MAIN_SVG"
    if [ "$SMALL_SVG" != "" ]; then
      cat "$FRONTEND_DIR/$SMALL_SVG"
    fi
  } | shasum -a 256 | awk '{print $1}'
)"
HASH="${hash_src:0:12}"

OUT_DIR="$FRONTEND_DIR/public/favicons/$HASH"
mkdir -p "$OUT_DIR"

render_svg_png() {
  local in="$1"
  local size="$2"
  local out="$3"
  rsvg-convert -w "$size" -h "$size" -o "$out" "$in"
}

FAVICON_SVG_PATH="$FRONTEND_DIR/$MAIN_SVG"
if [ "$SMALL_SVG" != "" ]; then
  FAVICON_SVG_PATH="$FRONTEND_DIR/$SMALL_SVG"
fi

cp "$FAVICON_SVG_PATH" "$OUT_DIR/favicon.svg"
render_svg_png "$FAVICON_SVG_PATH" 16  "$OUT_DIR/favicon-16.png"
render_svg_png "$FAVICON_SVG_PATH" 32  "$OUT_DIR/favicon-32.png"
render_svg_png "$FRONTEND_DIR/$MAIN_SVG" 180 "$OUT_DIR/apple-touch-icon.png"
render_svg_png "$FRONTEND_DIR/$MAIN_SVG" 192 "$OUT_DIR/android-chrome-192.png"
render_svg_png "$FRONTEND_DIR/$MAIN_SVG" 512 "$OUT_DIR/android-chrome-512.png"

cat > "$OUT_DIR/site.webmanifest" <<EOF
{
  "name": "Pantaray",
  "short_name": "Pantaray",
  "icons": [
    { "src": "android-chrome-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "android-chrome-512.png", "sizes": "512x512", "type": "image/png" }
  ],
  "theme_color": "#ffffff",
  "background_color": "#ffffff",
  "display": "standalone"
}
EOF

# HTML 側の参照を更新（Vite の base と両立させるため `%BASE_URL%` を利用）
sed_inplace() {
  local expr="$1"
  local target="$2"
  # GNU sed と BSD sed の -i 差分を吸収（Linux/CI でもローカルでも同じスクリプトを使える）
  if sed --version >/dev/null 2>&1; then
    sed -i -E "$expr" "$target"
  else
    sed -i '' -E "$expr" "$target"
  fi
}

update_html() {
  local target="$1"
  if [ ! -f "$target" ]; then
    return
  fi
  # 既存のハッシュ/プレースホルダを新ハッシュに置換（繰り返し実行しても更新できるようにする）
  sed_inplace "s/favicons\\/(__FAVICON_HASH__|[0-9a-f]{12})/favicons\\/$HASH/g" "$target"
}

update_html "$FRONTEND_DIR/index.html"
update_html "$FRONTEND_DIR/notification.html"

echo "favicon を生成しました: public/favicons/$HASH"
echo "HTML 参照を更新しました: index.html / notification.html"

