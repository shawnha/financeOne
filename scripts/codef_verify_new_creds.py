# CODEF 새 자격증명 검증 — 토큰발급/공개키암호화/실데이터조회 (env로 주입, .env·DB 무변경)
# 사용: CODEF_NEW_CLIENT_ID=.. CODEF_NEW_SECRET=.. CODEF_NEW_PUBKEY=.. python3 scripts/codef_verify_new_creds.py [biz_no]
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.services.integrations.codef import (  # noqa: E402
    CODEF_PRODUCTION_URL,
    CODEF_TOKEN_URL,
    CodefClient,
    CodefError,
    encrypt_password,
)

CID = os.environ["CODEF_NEW_CLIENT_ID"].strip()
SEC = os.environ["CODEF_NEW_SECRET"].strip()
PUB = os.environ["CODEF_NEW_PUBKEY"].strip()
BIZ = (sys.argv[1] if len(sys.argv) > 1 else "1968103665").strip()


def line(t):
    print("\n" + "=" * 64 + f"\n{t}\n" + "=" * 64)


# 1) 토큰 발급 (oauth.codef.io, Basic 인증) — 계정 활성/자격증명 유효성
line("1) 토큰 발급 테스트 (oauth.codef.io)")
try:
    r = httpx.post(
        CODEF_TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(CID, SEC),
        timeout=15.0,
    )
    print(f"  HTTP {r.status_code}")
    if r.status_code == 200:
        tok = r.json().get("access_token", "")
        print(f"  ✅ access_token 발급 성공 (len={len(tok)}, prefix={tok[:12]}...)")
        print(f"  scope={r.json().get('scope')} expires_in={r.json().get('expires_in')}")
    else:
        print(f"  ❌ 실패 body={r.text[:300]}")
        sys.exit(1)
except Exception as e:
    print(f"  ❌ 예외: {type(e).__name__}: {e}")
    sys.exit(1)

# 2) 공개키 RSA 암호화 (계정등록 시 비밀번호 암호화에 사용) — 키 유효성
line("2) 공개키 RSA 암호화 테스트")
try:
    enc = encrypt_password("verify_test_1234", PUB)
    print(f"  ✅ 공개키 정상 (PKCS1v15 암호화 OK, ciphertext_b64 len={len(enc)})")
except CodefError as e:
    print(f"  ❌ 공개키 오류: {e}")

# 3) 실데이터 조회 — 사업자 휴폐업 상태 (connectedId/인증서 불필요, 프로덕션)
line(f"3) 실데이터 조회 — 사업자상태 (biz_no={BIZ}, api.codef.io)")
client = CodefClient(CID, SEC, base_url=CODEF_PRODUCTION_URL)
try:
    res = client.check_business_status(BIZ)
    print("  ✅ 데이터 수신 성공:")
    for k in ("biz_no", "status", "status_code", "tax_type", "trade_name", "status_date"):
        print(f"     {k} = {res.get(k)}")
except CodefError as e:
    print(f"  ⚠️ CODEF 응답 오류: {e}")
    print(f"     code={e.code} tx={e.transaction_id} extra={e.extra_message}")
    print("     (토큰은 성공했으므로 자격증명은 유효. 해당 상품 미구독/권한 가능성)")
except Exception as e:
    print(f"  ❌ 예외: {type(e).__name__}: {e}")
finally:
    client.close()

print("\n[done] 검증 종료 — .env/코드/DB 무변경")
