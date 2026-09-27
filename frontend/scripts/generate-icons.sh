#!/bin/bash
set -euo pipefail

# このスクリプトは macOS 用の .icns を生成します。
#
# 使用法:
# - PNG入力（従来どおり）:
#     ./generate-icons.sh path/to/icon.png
# - SVG入力（サイズ別の最適化が可能）:
#     ./generate-icons.sh path/to/icon.svg [path/to/icon_small.svg]
#
# 備考:
# - SVG入力時のみ `rsvg-convert` が必要です
# - `icon_small.svg` を渡すと、16/32px向けに小サイズ最適化SVGを利用します

if [ "${1:-}" = "" ]; then
  echo "使用法: $0 path/to/icon.(png|svg) [path/to/icon_small.svg]" >&2
  exit 1
fi

INPUT_FILE="$1"
SMALL_FILE="${2:-}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "必要なコマンドが見つかりません: $1" >&2
    exit 2
  fi
}

require_cmd iconutil
require_cmd mktemp
require_cmd sips

ICONSET="$(mktemp -d)/icon.iconset"
mkdir -p "$ICONSET"

SRGB_PROFILE="/System/Library/ColorSync/Profiles/sRGB Profile.icc"
if [ ! -f "$SRGB_PROFILE" ]; then
  echo "sRGB プロファイルが見つかりません: $SRGB_PROFILE" >&2
  exit 2
fi

# PNG に色プロファイルが無い場合、明示的に sRGB を付与して “見え方のブレ” を防ぐ。
# 背景:
# - プロファイル無しPNGは、表示環境/ツールによって解釈が揺れる（結果として薄く/濃く見える）。
# - アイコン生成（sips/iconutil）過程で sRGB が付与されることがあり、元画像と見え方がズレる。
# 方針:
# - 生成元/生成物の双方に sRGB を付与して、常に同じ前提で色管理させる。
#
# - 元画像に別プロファイルが付いている場合は、sRGB に変換してから埋め込む。
ensure_srgb_profile() {
  local target="$1"
  local tmp="/tmp/pantaray_icon_srgb.$RANDOM.$RANDOM.png"
  local profile=""
  profile="$(sips -g profile "$target" | awk -F': ' '/profile:/ {print $2}')"
  if [ "$profile" = "sRGB IEC61966-2.1" ]; then
    return
  fi
  if [ "$profile" = "<nil>" ] || [ "$profile" = "" ]; then
    sips -e "$SRGB_PROFILE" "$target" --out "$tmp" >/dev/null
  else
    sips -m "$SRGB_PROFILE" "$target" --out "$tmp" >/dev/null
  fi
  mv "$tmp" "$target"
}

render_png() {
  local in="$1"
  local size="$2"
  local out="$3"
  sips -z "$size" "$size" "$in" --out "$out" >/dev/null
  ensure_srgb_profile "$out"
}

render_svg() {
  local in="$1"
  local size="$2"
  local out="$3"
  rsvg-convert -w "$size" -h "$size" -o "$out" "$in"
  ensure_srgb_profile "$out"
}

gen_icons_from_png() {
  local in="$1"
  render_png "$in" 16   "$ICONSET/icon_16x16.png"
  render_png "$in" 32   "$ICONSET/icon_16x16@2x.png"
  render_png "$in" 32   "$ICONSET/icon_32x32.png"
  render_png "$in" 64   "$ICONSET/icon_32x32@2x.png"
  render_png "$in" 128  "$ICONSET/icon_128x128.png"
  render_png "$in" 256  "$ICONSET/icon_128x128@2x.png"
  render_png "$in" 256  "$ICONSET/icon_256x256.png"
  render_png "$in" 512  "$ICONSET/icon_256x256@2x.png"
  render_png "$in" 512  "$ICONSET/icon_512x512.png"
  render_png "$in" 1024 "$ICONSET/icon_512x512@2x.png"
}

gen_icons_from_svg() {
  require_cmd rsvg-convert
  local in="$1"
  local small="$2"
  local in_16="$in"
  local in_32="$in"
  if [ "$small" != "" ]; then
    in_16="$small"
    in_32="$small"
  fi

  render_svg "$in_16" 16   "$ICONSET/icon_16x16.png"
  render_svg "$in_16" 32   "$ICONSET/icon_16x16@2x.png"
  render_svg "$in_32" 32   "$ICONSET/icon_32x32.png"
  render_svg "$in_32" 64   "$ICONSET/icon_32x32@2x.png"
  render_svg "$in"    128  "$ICONSET/icon_128x128.png"
  render_svg "$in"    256  "$ICONSET/icon_128x128@2x.png"
  render_svg "$in"    256  "$ICONSET/icon_256x256.png"
  render_svg "$in"    512  "$ICONSET/icon_256x256@2x.png"
  render_svg "$in"    512  "$ICONSET/icon_512x512.png"
  render_svg "$in"    1024 "$ICONSET/icon_512x512@2x.png"
}

case "$INPUT_FILE" in
  *.png|*.PNG)
    gen_icons_from_png "$INPUT_FILE"
    ;;
  *.svg|*.SVG)
    gen_icons_from_svg "$INPUT_FILE" "$SMALL_FILE"
    ;;
  *)
    echo "未対応の拡張子です: $INPUT_FILE（png/svgのみ対応）" >&2
    exit 3
    ;;
esac

iconutil -c icns "$ICONSET"
cp "$(dirname "$ICONSET")/icon.icns" "$(dirname "$0")/../build/icon.icns"
rm -rf "$(dirname "$ICONSET")"

echo "アイコンが正常に生成されました: $(dirname "$0")/../build/icon.icns"