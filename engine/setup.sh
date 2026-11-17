#!/usr/bin/env bash
# Showdown(포챔스 모드 포함)을 고정된 커밋으로 받아 빌드한다. Node 18+ 와 git, 인터넷이 필요하다.
set -euo pipefail
cd "$(dirname "$0")"
COMMIT="$(cat SHOWDOWN_COMMIT)"
if [ ! -d .showdown/.git ]; then
  git clone --filter=blob:none https://github.com/smogon/pokemon-showdown .showdown
fi
cd .showdown
git fetch -q origin "$COMMIT" 2>/dev/null || git fetch -q origin
git checkout -q "$COMMIT"
npm install --omit=dev --no-audit --no-fund
node build
echo "Showdown 준비 완료: $COMMIT"
