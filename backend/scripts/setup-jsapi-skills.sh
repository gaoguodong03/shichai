#!/bin/bash
# 安装百度地图 JSAPI Skills 到 DHA backend/skills
# 来源: https://github.com/baidu-maps/jsapi-skills

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILLS_DIR="$BACKEND_DIR/skills"
TMP_DIR=$(mktemp -d)

echo "克隆 jsapi-skills 仓库..."
git clone --depth 1 https://github.com/baidu-maps/jsapi-skills.git "$TMP_DIR"

echo "复制 Skills 到 $SKILLS_DIR ..."
for skill in bmap-jsapi-gl bmap-jsapi-three jsapi-ui-kit; do
  if [ -d "$TMP_DIR/$skill" ]; then
    rm -rf "$SKILLS_DIR/$skill"
    cp -r "$TMP_DIR/$skill" "$SKILLS_DIR/"
    echo "  ✓ $skill"
  fi
done

rm -rf "$TMP_DIR"
echo "完成。百度地图 JSAPI Skills 已安装到 backend/skills/"
echo "  - bmap-jsapi-gl: 百度地图 JSAPI WebGL 版"
echo "  - bmap-jsapi-three: 百度地图 JSAPI Three 版 (MapVThree)"
echo "  - jsapi-ui-kit: 百度地图 UI 组件库"
