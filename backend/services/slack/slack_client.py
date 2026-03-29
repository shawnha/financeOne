"""Slack API 클라이언트 — 채널 히스토리 + 쓰레드 + 유저 프로필 + 리액션"""

import time
import requests
from pathlib import Path


def _get_token() -> str:
    env_path = Path(__file__).resolve().parents[3] / ".env"
    for line in env_path.read_text().splitlines():
        if line.startswith("SLACK_BOT_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("SLACK_BOT_TOKEN not found in .env")


def _headers() -> dict:
    return {"Authorization": f"Bearer {_get_token()}"}


def _api_get(url: str, params: dict) -> dict:
    """Slack API GET with rate limit handling."""
    for attempt in range(3):
        resp = requests.get(url, headers=_headers(), params=params, timeout=10)
        data = resp.json()
        if data.get("ok"):
            return data
        if data.get("error") == "ratelimited":
            retry_after = int(resp.headers.get("Retry-After", 5))
            time.sleep(retry_after)
            continue
        if data.get("error") == "invalid_auth":
            raise RuntimeError("Slack 토큰이 만료되었거나 유효하지 않습니다. .env의 SLACK_BOT_TOKEN을 확인하세요.")
        if data.get("error") == "not_in_channel":
            raise RuntimeError("봇이 채널에 초대되지 않았습니다. Slack에서 봇을 채널에 추가해주세요.")
        if data.get("error") == "channel_not_found":
            raise RuntimeError(f"채널을 찾을 수 없습니다: {params.get('channel', '?')}")
        raise RuntimeError(f"Slack API error: {data.get('error')}")
    raise RuntimeError("Slack API rate limit exceeded after 3 retries")


def find_channel_id(channel_name: str) -> str:
    """채널 이름으로 ID 조회."""
    data = _api_get("https://slack.com/api/conversations.list", {"types": "public_channel,private_channel", "limit": 200})
    for ch in data["channels"]:
        if ch["name"] == channel_name:
            return ch["id"]
    raise RuntimeError(f"채널 #{channel_name}을 찾을 수 없습니다")


def fetch_history(channel_id: str) -> list[dict]:
    """채널 전체 히스토리 (페이지네이션)."""
    all_messages = []
    cursor = None
    while True:
        params = {"channel": channel_id, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        data = _api_get("https://slack.com/api/conversations.history", params)
        all_messages.extend(data["messages"])
        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
        time.sleep(1)
    return all_messages


def fetch_replies(channel_id: str, thread_ts: str) -> list[dict]:
    """쓰레드 댓글 조회 (부모 메시지 제외)."""
    data = _api_get("https://slack.com/api/conversations.replies", {"channel": channel_id, "ts": thread_ts})
    return data["messages"][1:]


def fetch_user_name(user_id: str) -> str:
    """Slack user ID → real_name."""
    data = _api_get("https://slack.com/api/users.info", {"user": user_id})
    user = data["user"]
    return user.get("real_name") or user.get("profile", {}).get("display_name") or user_id


def get_reactions(message: dict) -> list[str]:
    """메시지의 리액션 이름 목록."""
    return [r["name"] for r in message.get("reactions", [])]
