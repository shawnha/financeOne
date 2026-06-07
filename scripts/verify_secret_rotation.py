# 로테이션한 자격증명이 유효한지 읽기전용으로 검증 (토큰 발급/단건 조회만, DB 무변경)
"""
사용:
  python3 scripts/verify_secret_rotation.py codef
  python3 scripts/verify_secret_rotation.py gowid
  python3 scripts/verify_secret_rotation.py ssart
  python3 scripts/verify_secret_rotation.py all

.env 를 새로 로드하므로 running 백엔드 재시작 불필요. 비밀 값은 출력하지 않는다.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(override=True)  # .env 를 강제로 다시 읽음 (교체된 값 반영)


def check_codef() -> bool:
    from backend.services.integrations.codef import (
        get_credentials_for_env,
        CodefClient,
        CODEF_PRODUCTION_URL,
    )
    cid, sec, pk = get_credentials_for_env("production")
    if not cid or not sec:
        print("CODEF  ❌ CODEF_PROD_CLIENT_ID/SECRET 미설정")
        return False
    client = CodefClient(cid, sec, base_url=CODEF_PRODUCTION_URL)
    try:
        token = client._get_token()
        ok = bool(token)
        print(f"CODEF  {'✅' if ok else '❌'} OAuth 토큰 발급 {'성공' if ok else '실패'} (secret 유효)")
        return ok
    except Exception as e:
        print(f"CODEF  ❌ 토큰 발급 실패: {e}")
        return False
    finally:
        client.close()


def check_gowid() -> bool:
    from backend.services.integrations.gowid import GowidClient
    key = os.environ.get("GOWID_API_KEY", "").strip()
    if not key:
        print("GOWID  ❌ GOWID_API_KEY 미설정")
        return False
    client = GowidClient(key)
    try:
        ok = client.health()  # /v1/members 단건 호출
        print(f"GOWID  {'✅' if ok else '❌'} /v1/members 조회 {'성공' if ok else '실패'} (API key 유효)")
        return ok
    finally:
        client.close()


def check_ssart() -> bool:
    from backend.services.integrations.ssart import SsArtClient, SsArtError
    try:
        with SsArtClient() as c:
            token = c.authenticate()  # 2단계 인증
            ok = bool(token)
            print(f"SSART  {'✅' if ok else '❌'} 인증 토큰 발급 {'성공' if ok else '실패'} (UID/PWD 유효)")
            return ok
    except SsArtError as e:
        print(f"SSART  ❌ 인증 실패: {e}")
        return False


CHECKS = {"codef": check_codef, "gowid": check_gowid, "ssart": check_ssart}


def main() -> int:
    target = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    targets = list(CHECKS) if target == "all" else [target]
    if any(t not in CHECKS for t in targets):
        print(f"대상은 {list(CHECKS)} 또는 all")
        return 2
    results = [CHECKS[t]() for t in targets]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
