#!/usr/bin/env bash
# Vercel financeone-api 프로젝트에 환경변수 일괄 등록 스크립트.
# 사용: bash scripts/setup_vercel_env.sh
#
# 전제:
#   - 프로젝트 루트의 ../.env (또는 ./.env) 에서 값 읽음
#   - vercel CLI 가 financeone-api 에 link 되어 있어야 (backend/.vercel 폴더 존재)
#
# 등록 변수:
#   DATABASE_URL, ANTHROPIC_API_KEY, CODEF_CLIENT_ID, CODEF_CLIENT_SECRET,
#   CODEF_PUBLIC_KEY (multiline RSA), CODEF_ENV
#   + HOI_ENTITY_ID=1, ALLOWED_ORIGINS, DISABLE_SCHEDULER=1

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
ENV_FILE="$PROJECT_ROOT/.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "✗ .env not found at $ENV_FILE"
  exit 1
fi

if [ ! -d "$BACKEND_DIR/.vercel" ]; then
  echo "✗ backend/.vercel not found — run 'cd backend && vercel link' first"
  exit 1
fi

cd "$BACKEND_DIR"

# Read single-line values
get_env() {
  grep -E "^$1=" "$ENV_FILE" | head -1 | sed -E "s/^$1=//; s/^\"//; s/\"$//"
}

DATABASE_URL=$(get_env DATABASE_URL)
ANTHROPIC_API_KEY=$(get_env ANTHROPIC_API_KEY)
CODEF_CLIENT_ID=$(get_env CODEF_CLIENT_ID)
CODEF_CLIENT_SECRET=$(get_env CODEF_CLIENT_SECRET)
CODEF_ENV_VAL=$(get_env CODEF_ENV)

# Read multiline CODEF_PUBLIC_KEY (PEM block)
CODEF_PUBLIC_KEY=$(awk '
  /^CODEF_PUBLIC_KEY=/ {found=1; sub(/^CODEF_PUBLIC_KEY=/,""); sub(/^"/,""); print; next}
  found && /^[A-Z_]+=/ {exit}
  found {print}
' "$ENV_FILE")
# strip trailing quote if any
CODEF_PUBLIC_KEY="${CODEF_PUBLIC_KEY%\"}"

# Validate
for K in DATABASE_URL ANTHROPIC_API_KEY CODEF_CLIENT_ID CODEF_CLIENT_SECRET CODEF_ENV_VAL CODEF_PUBLIC_KEY; do
  eval V=\$$K
  if [ -z "$V" ]; then
    echo "✗ $K is empty — check .env"
    exit 1
  fi
done

echo "✓ Read 6 secrets from $ENV_FILE"
echo

# Register all envs across production, preview, development
register() {
  local KEY="$1"
  local VALUE="$2"
  local TARGET="$3"
  printf "%s" "$VALUE" | vercel env add "$KEY" "$TARGET" --force >/dev/null 2>&1 \
    && echo "  ✓ $KEY ($TARGET)" \
    || echo "  ✗ $KEY ($TARGET) failed"
}

for TARGET in production preview development; do
  echo "── target: $TARGET ──"
  register DATABASE_URL        "$DATABASE_URL"        "$TARGET"
  register ANTHROPIC_API_KEY   "$ANTHROPIC_API_KEY"   "$TARGET"
  register CODEF_CLIENT_ID     "$CODEF_CLIENT_ID"     "$TARGET"
  register CODEF_CLIENT_SECRET "$CODEF_CLIENT_SECRET" "$TARGET"
  register CODEF_PUBLIC_KEY    "$CODEF_PUBLIC_KEY"    "$TARGET"
  register CODEF_ENV           "$CODEF_ENV_VAL"       "$TARGET"
  register HOI_ENTITY_ID       "1"                    "$TARGET"
  register ALLOWED_ORIGINS     "https://financesone.vercel.app" "$TARGET"
  register DISABLE_SCHEDULER   "1"                    "$TARGET"
  echo
done

echo "──────────────────────────────────────────"
echo "✓ All envs registered. Triggering redeploy..."
echo

vercel --prod
