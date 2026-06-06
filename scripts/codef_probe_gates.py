# CODEF 프로덕션 키 작동검증 — 토큰발급 + 상품권한 게이트(connectedId 없이) + 데모 거부 확인 (읽기전용, .env·DB 무변경)
# 사용: CODEF_NEW_CLIENT_ID=.. CODEF_NEW_SECRET=.. python3 scripts/codef_probe_gates.py
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.services.integrations.codef import (  # noqa: E402
    CODEF_DEMO_URL,
    CODEF_PRODUCTION_URL,
    CODEF_TOKEN_URL,
    CodefClient,
    CodefError,
)

CID = os.environ["CODEF_NEW_CLIENT_ID"].strip()
SEC = os.environ["CODEF_NEW_SECRET"].strip()
DUMMY_CONN = "00000000-0000-0000-0000-000000000000"  # 존재하지 않는 connectedId


def line(t):
    print("\n" + "=" * 66 + f"\n{t}\n" + "=" * 66)


def probe(client, label, endpoint, params):
    """endpoint 를 더미 connectedId 로 호출 → CF 코드로 권한 판별."""
    try:
        client._request(endpoint, params)
        print(f"  {label:32s} → ✅ 200 (데이터수신)")
    except CodefError as e:
        code = e.code or "?"
        meaning = {
            "CF-04015": "✅ 상품권한 OK (connectedId 미존재 — 등록만 하면 조회됨)",
            "CF-00401": "❌ 상품 미신청/권한없음",
            "CF-00005": "⛔ 도메인 거부 (이 키는 이 서버용 아님)",
            "CF-12829": "✅ 권한 OK (법인은행 공동인증서 필요)",
        }.get(code, f"⚠️ {e.extra_message or ''}")
        print(f"  {label:32s} → {code}  {meaning}")
    except Exception as e:
        print(f"  {label:32s} → ❌ {type(e).__name__}: {e}")


# 1) 토큰 발급 (oauth.codef.io) — 자격증명 자체 유효성
line("1) 토큰 발급 (oauth.codef.io, HTTP Basic)")
r = httpx.post(CODEF_TOKEN_URL, data={"grant_type": "client_credentials"}, auth=(CID, SEC), timeout=15.0)
print(f"  HTTP {r.status_code}")
if r.status_code == 200:
    j = r.json()
    tok = j.get("access_token", "")
    print(f"  ✅ access_token 발급 (len={len(tok)}, prefix={tok[:10]}..., scope={j.get('scope')}, expires_in={j.get('expires_in')}s)")
else:
    print(f"  ❌ 실패 {r.text[:200]}")
    sys.exit(1)

# 2) 프로덕션 상품 권한 게이트 (connectedId 없이 — 권한게이트만 통과여부 판별)
line(f"2) 프로덕션 상품 권한 ({CODEF_PRODUCTION_URL}) — 더미 connectedId")
prod = CodefClient(CID, SEC, base_url=CODEF_PRODUCTION_URL)
try:
    probe(prod, "은행 거래내역 transaction-list", "/v1/kr/bank/b/account/transaction-list",
          {"connectedId": DUMMY_CONN, "organization": "0020", "account": "0000000000000",
           "startDate": "20260601", "endDate": "20260605", "orderBy": "0", "inquiryType": "1"})
    probe(prod, "카드 승인내역 approval-list", "/v1/kr/card/b/account/approval-list",
          {"connectedId": DUMMY_CONN, "organization": "0309", "startDate": "20260601",
           "endDate": "20260605", "inquiryType": "0", "orderBy": "0", "cardNo": "0000000000000000"})
    probe(prod, "은행 보유계좌목록 account-list", "/v1/kr/bank/b/account/account-list",
          {"connectedId": DUMMY_CONN, "organization": "0020"})
    probe(prod, "카드 보유카드목록 card-list", "/v1/kr/card/b/account/card-list",
          {"connectedId": DUMMY_CONN, "organization": "0309"})
finally:
    prod.close()

# 3) 데모 서버 거부 확인 — 이 키가 프로덕션 전용인지
line(f"3) 데모 서버 거부 확인 ({CODEF_DEMO_URL})")
demo = CodefClient(CID, SEC, base_url=CODEF_DEMO_URL)
try:
    probe(demo, "데모 transaction-list", "/v1/kr/bank/b/account/transaction-list",
          {"connectedId": DUMMY_CONN, "organization": "0020", "account": "0000000000000",
           "startDate": "20260601", "endDate": "20260605", "orderBy": "0", "inquiryType": "1"})
finally:
    demo.close()

print("\n[done] 읽기전용 게이트 검증 종료 — .env/코드/DB 무변경")
print("판별: CF-04015=권한OK(connectedId만 등록하면 실조회) / CF-00401=미신청 / CF-00005=서버불일치")
