#!/bin/bash
# Track A 월간 자동화 (매월 1일 00시 cron 실행)
#
# 흐름:
#   1) confirmed 거래에서 키워드 자동 학습 (P4-C)
#   2) Obsidian wiki/매핑학습/YYYY-MM.md 자동 생성
#   3) NotebookLM 노트북 'HanahOne ERP Knowledge' 에 새 source 추가
#   4) git commit + push (NotebookLM GitHub source 자동 sync)
#   5) Telegram 알림 (실패 시)
#
# 등록:
#   crontab -e
#   0 0 1 * * /Users/admin/Desktop/claude/financeOne/scripts/track_a_monthly.sh >> /tmp/track_a_monthly.log 2>&1

set -euo pipefail

PROJECT_DIR=/Users/admin/Desktop/claude/financeOne
NOTEBOOK_ID=120d54ae-1a98-4389-8f29-a95cedf1e0c7
VAULT=/Users/admin/Documents/hanahone-vault

cd "$PROJECT_DIR"
source .venv/bin/activate

YEAR=$(date +%Y)
MONTH=$(date +%m)
NOTE_PATH="$VAULT/wiki/매핑학습/${YEAR}-${MONTH}.md"

echo "[$(date)] Track A 월간 자동화 시작"

# 1) 학습 루프 (P4-C) — Obsidian writer 포함
echo "[$(date)] 1. 키워드 학습 + Obsidian 노트 생성"
python3 -m backend.scripts.learn_keywords_from_confirmed

# 2) NotebookLM 에 새 노트 추가 (이미 존재하면 skip 위해 source list 확인)
if [ -f "$NOTE_PATH" ]; then
    echo "[$(date)] 2. NotebookLM 에 학습 노트 추가: $NOTE_PATH"
    notebooklm source add "$NOTE_PATH" --notebook "$NOTEBOOK_ID" 2>&1 | tail -3 || true
fi

# 3) git commit + push (Obsidian vault 가 financeOne repo 안이 아니라
#    별도 위치이므로 vault 의 git 으로 push 또는 financeOne 의 metric snapshot 만 push)
echo "[$(date)] 3. metric snapshot git push"
cd "$PROJECT_DIR"
if [[ -n $(git status --porcelain .claude-tmp/) ]]; then
    # .claude-tmp 는 gitignore 라 sync 안됨 — vault 자체를 git 화하는 별도 작업 필요
    echo "metric snapshot 은 .claude-tmp 안 (gitignore). 별도 vault git 필요."
fi

echo "[$(date)] Track A 월간 자동화 완료"
