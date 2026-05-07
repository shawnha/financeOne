# FinanceOne — 도매 매출/매입 자동 업로드 API

외부 자동화 프로그램 (cron, RPA, ETL job) 이 매출관리/매입관리 xlsx 를 주기적으로 FinanceOne 에 업로드할 때 사용하는 endpoint 명세.

**Base URL**:
- Production: `https://financeone-api.vercel.app/api` (Vercel `financeone-api` 프로젝트, icn1 region)
- Local dev: `http://localhost:8000/api`

> 참고 — frontend 는 별도 배포: `https://financesone.vercel.app` (외부 자동 업로드 프로그램은 frontend 가 아니라 위 backend URL 직접 호출)

**Last updated**: 2026-05-07

---

## 1. 인증

옵션 — 환경변수 `FINANCEONE_API_KEY` 가 서버에 설정되어 있을 때만 강제됨.

| 환경 | 동작 |
|---|---|
| `FINANCEONE_API_KEY` **미설정** | 인증 없이 호출 가능 (개발/내부망 전용) |
| `FINANCEONE_API_KEY` **설정** | 모든 요청에 `X-API-Key: <key>` 헤더 필수. 미일치 시 `401 Unauthorized` |

> ⚠️ **현재 상태**: env 미설정 → 누구나 인증 없이 호출 가능. 외부 자동화 프로그램과 연동하기 전 반드시 아래 §1.3 절차로 key 발급·설정.

### 1.1 API Key 생성 (운영자가 직접 실행)

API key 는 **절대 repo / 슬랙 / 일반 이메일에 평문 commit/공유 금지**. 본인 로컬에서 생성:

```bash
# macOS / Linux — 64자 hex (256-bit)
openssl rand -hex 32
# 출력 예 (이건 예시 — 본인이 다시 생성해서 사용):
# 7c4d8a2b9e1f5a3c6d8b2e9f4a7c1d5e8b3f6a9c2d4e7f1a8b5c3d9e6f2a4b1c
```

```powershell
# Windows PowerShell
-join ((48..57) + (97..102) | Get-Random -Count 64 | ForEach-Object {[char]$_})
```

```python
# Python (cross-platform)
python3 -c "import secrets; print(secrets.token_hex(32))"
```

생성된 값은 **1Password / Bitwarden** 등 비밀번호 관리자에 즉시 저장.

### 1.2 Vercel 서버에 설정

#### 옵션 A — Vercel Dashboard (권장)
1. https://vercel.com → FinanceOne 프로젝트 → Settings → Environment Variables
2. `Add New`
3. **Key**: `FINANCEONE_API_KEY`
4. **Value**: §1.1 에서 생성한 64자 hex
5. **Environments**: Production / Preview / Development 모두 체크
6. Save → 새 deployment 트리거 (env 는 build time 반영) — Deployments 탭에서 `Redeploy` 클릭

#### 옵션 B — Vercel CLI
```bash
# Vercel CLI 설치 필요: npm i -g vercel
vercel link  # 프로젝트 연결 (1회)
vercel env add FINANCEONE_API_KEY production
# 프롬프트에 §1.1 에서 생성한 key 붙여넣기

# preview/development 도 같은 key 로 설정 (권장)
vercel env add FINANCEONE_API_KEY preview
vercel env add FINANCEONE_API_KEY development

# 변경 반영
vercel --prod
```

### 1.3 외부 자동화 프로그램에 전달

서버에 설정한 동일한 key 를 외부 프로그램에 안전하게 전달:

✅ **권장**:
- 1Password / Bitwarden 의 secure note 공유
- Signal / 텔레그램 self-destruct 메시지
- 직접 만남 / 전화 받아쓰기

❌ **금지**:
- 카카오톡 / 일반 이메일 / 슬랙 평문 메시지
- git commit / GitHub issue / 노션 page
- 캡쳐화면 (URL bar / 터미널 출력)

외부 프로그램 측 설정 예시:
```bash
# .env (gitignore 처리 필수)
FINANCEONE_API_KEY=<§1.1에서 생성한 동일한 key>
```

```python
# Python — env 사용
import os
key = os.environ["FINANCEONE_API_KEY"]
```

### 1.4 회전 (Rotation)

- **권장 주기**: 6 ~ 12 개월 1회 또는 직원 퇴사·외부 업체 교체 시 즉시
- **회전 절차**:
  1. §1.1 절차로 새 key 생성
  2. Vercel env 의 `FINANCEONE_API_KEY` 값을 새 key 로 교체 + redeploy
  3. 외부 프로그램 측도 동시에 새 key 로 교체 (다운타임 < 1분)
  4. (지금은 단일 key 라 zero-downtime 회전 불가 — 향후 다중 key 지원 시 grace period rotation 가능)

### 1.5 보안 체크리스트

- [ ] `openssl rand -hex 32` 등으로 cryptographically secure 한 64자 hex key 생성
- [ ] 1Password / Bitwarden 등에 즉시 저장
- [ ] Vercel env 에 설정 (Production + Preview + Development)
- [ ] 외부 프로그램의 `.env` (gitignore 됨) 또는 secret manager 에 설정
- [ ] **commit/공유 절대 금지**: git, 카톡, 일반 이메일, 슬랙 평문
- [ ] 6~12개월마다 회전
- [ ] 의심스러운 활동 감지 시 즉시 회전 (서버 로그에 새 IP 등)

### 1.6 (참고) 향후 계획

- 다중 API key 지원 (entity별 / 외부 프로그램별 분리)
- key 별 rate limit / 호출 로그
- Grace period rotation (구 key 와 신 key 동시 유효 기간)

위 기능 필요해지면 별도 issue 등록.

---

## 2. 매출관리 업로드

### `POST /api/upload/wholesale-sales`

매출관리 xlsx 파일을 적재. 동일 `(entity_id, sales_date, document_no, row_number, product_name)` 키 중복은 자동 skip (멱등 보장).

#### Request

| 항목 | 타입 | 위치 | 설명 |
|---|---|---|---|
| `entity_id` | integer | query | 법인 ID (한아원홀세일=13, 한아원코리아=2, 한아원리테일=3, HOI=1) |
| `file` | file | multipart/form-data | `.xlsx` 또는 `.xls`. 최대 10MB |
| `X-API-Key` | string | header | (옵션) 서버에서 인증 활성화 시 필수 |

#### 필요한 xlsx 포맷 (한아원홀세일 매출관리 양식 기준)

48 column. row 1 헤더, row 3 부터 데이터. col 7 (매출구분) 이 `"매출"` 인 row 만 적재.

주요 컬럼 (Excel letter):
| 컬럼 | 헤더 | 의미 | 필수? |
|:---:|---|---|:---:|
| B | 매출일자 | 매출 발생일 | ✓ |
| F | 거래처명 | 매출 대상 | ✓ |
| G | 매출구분 | "매출" 이어야 import | ✓ |
| I | 제 품 명 | 제품명 | ✓ |
| K | 수량 | qty | |
| Q | 합계금액 | 매출액 (VAT 포함) | |
| AO | 매입가(장부) | 매출원가 단가 | (마진 계산용) |
| AP | 매입가(실) | 실매입 단가 | (검증용) |

#### 응답 (200 OK)

```json
{
  "filename": "4월매출관리(한아원홀세일).xlsx",
  "entity_id": 13,
  "total_rows": 1073,
  "inserted": 1073,
  "duplicates": 0,
  "errors": [],
  "sample": [
    {
      "id": 12345,
      "date": "2026-04-01",
      "payee": "동탄)동탄아이엠유의원",
      "product": "릴리)마운자로 펜 5mg/0.5ml/4관",
      "total": 5867500
    }
  ],
  "alerts": {
    "cogs_book_vs_real_diff": {
      "count": 1,
      "total_diff": 0,
      "examples": [
        {
          "date": "2026-04-22",
          "payee": "동탄)동탄아이엠유의원",
          "product": "GSK)하브릭스 시린지 1ml/1관(생)",
          "qty": 5,
          "cogs_book": 33840,
          "cogs_real": 33840,
          "diff": 0
        }
      ]
    },
    "negative_margin": {
      "count": 20,
      "rows": [
        {
          "date": "2026-04-01",
          "payee": "동탄)동탄호수약국",
          "product": "...",
          "qty": 1,
          "total": 210500,
          "cogs_total": 211398,
          "margin": -898
        }
      ]
    },
    "missing_cogs": {
      "count": 20,
      "rows": [...]
    }
  }
}
```

#### `alerts` 필드 의미

| 키 | 의미 | 액션 |
|---|---|---|
| `cogs_book_vs_real_diff` | 매입가(장부) ≠ 매입가(실) | 가격 변동 추적 (info) |
| `negative_margin` | 매출액 < 매출원가 | 손실 판매 검토 (loss leader / 재고 처분 / 매입가 오기재 의심) |
| `missing_cogs` | 매입가(장부) 누락 | 매출원가 미반영 — 매출관리 xlsx 의 col AO 비어있음 |

자동화 프로그램은 `alerts.negative_margin.count > 0` 또는 `alerts.missing_cogs.count > 0` 일 때 슬랙/이메일로 운영자에게 알림 보내는 로직 추가 권장.

#### 응답 코드

| 코드 | 설명 |
|---|---|
| `200` | 성공 (inserted/duplicates/errors 확인) |
| `400` | 파일 포맷 오류 (xlsx/xls 아님 / 빈 파일 / 파싱 실패 / 매출 row 0건) |
| `401` | API key 누락 또는 불일치 |
| `500` | DB import 실패 (errors 배열 참조) |

---

## 3. 매입관리 업로드

### `POST /api/upload/wholesale-purchases`

매입관리 xlsx 파일을 적재. 매출과 동일한 멱등성/응답 구조.

#### Request

매출과 동일. 단 파일 포맷은 매입관리 양식 (40 column).

#### 매입 alerts

| 키 | 의미 |
|---|---|
| `unit_price_book_vs_real_diff` | 매입단가 장부 vs 실 차이 |
| `missing_unit_price` | 매입단가 누락 |

---

## 4. 호출 예시

### curl

```bash
# 매출 업로드
curl -X POST \
  "https://financeone-api.vercel.app/api/upload/wholesale-sales?entity_id=13" \
  -H "X-API-Key: $FINANCEONE_API_KEY" \
  -F "file=@/path/to/4월매출관리.xlsx"

# 매입 업로드
curl -X POST \
  "https://financeone-api.vercel.app/api/upload/wholesale-purchases?entity_id=13" \
  -H "X-API-Key: $FINANCEONE_API_KEY" \
  -F "file=@/path/to/4월매입관리.xlsx"
```

### Python (`requests`)

```python
import os
import requests

API_BASE = "https://financeone-api.vercel.app/api"
HEADERS = {"X-API-Key": os.environ["FINANCEONE_API_KEY"]}

def upload_sales(entity_id: int, xlsx_path: str) -> dict:
    with open(xlsx_path, "rb") as f:
        r = requests.post(
            f"{API_BASE}/upload/wholesale-sales",
            params={"entity_id": entity_id},
            files={"file": (os.path.basename(xlsx_path), f,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=HEADERS,
            timeout=120,
        )
    r.raise_for_status()
    return r.json()

def upload_purchases(entity_id: int, xlsx_path: str) -> dict:
    with open(xlsx_path, "rb") as f:
        r = requests.post(
            f"{API_BASE}/upload/wholesale-purchases",
            params={"entity_id": entity_id},
            files={"file": (os.path.basename(xlsx_path), f,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=HEADERS,
            timeout=120,
        )
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    sales = upload_sales(13, "/Users/admin/Downloads/4월매출관리(한아원홀세일).xlsx")
    print(f"매출 적재: {sales['inserted']}/{sales['total_rows']}건 (중복 {sales['duplicates']})")
    a = sales.get("alerts", {})
    if a.get("negative_margin", {}).get("count", 0) > 0:
        print(f"⚠️ 손실 판매 {a['negative_margin']['count']}건 감지")
    if a.get("missing_cogs", {}).get("count", 0) > 0:
        print(f"⚠️ 매입가 누락 {a['missing_cogs']['count']}건")
```

### Node.js (`form-data` + `axios`)

```javascript
const fs = require("fs");
const path = require("path");
const FormData = require("form-data");
const axios = require("axios");

const API_BASE = "https://financeone-api.vercel.app/api";
const API_KEY = process.env.FINANCEONE_API_KEY;

async function uploadSales(entityId, xlsxPath) {
  const fd = new FormData();
  fd.append("file", fs.createReadStream(xlsxPath), path.basename(xlsxPath));
  const res = await axios.post(
    `${API_BASE}/upload/wholesale-sales`,
    fd,
    {
      params: { entity_id: entityId },
      headers: { ...fd.getHeaders(), "X-API-Key": API_KEY },
      timeout: 120_000,
    },
  );
  return res.data;
}

(async () => {
  const result = await uploadSales(13, "/path/to/매출관리.xlsx");
  console.log(`매출 적재: ${result.inserted}/${result.total_rows}건`);
  const a = result.alerts || {};
  if ((a.negative_margin?.count ?? 0) > 0)
    console.warn(`⚠️ 손실 판매 ${a.negative_margin.count}건`);
})();
```

---

## 5. 자동화 패턴

### cron (Linux / macOS)

```cron
# 매일 오전 9시에 어제까지의 매출/매입 xlsx 업로드
0 9 * * * /usr/local/bin/python3 /opt/financeone-uploader/uploader.py >> /var/log/financeone-upload.log 2>&1
```

### Windows 작업 스케줄러

```powershell
# 매일 오전 9:00 실행
schtasks /create /tn "FinanceOne 자동 업로드" `
  /tr "python C:\financeone-uploader\uploader.py" `
  /sc daily /st 09:00
```

### 권장 patterns

1. **idempotent 호출** — 같은 파일을 여러 번 업로드해도 안전 (DB 중복 키 자동 skip). `duplicates > 0` 이 정상.
2. **alert 모니터링** — `alerts.negative_margin.count > 0` 또는 `alerts.missing_cogs.count > 0` 일 때 운영자 알림 (Slack webhook / 이메일 / SMS) 발송 권장.
3. **재시도 정책** — 5xx 응답 시 30초 후 1회 재시도. 4xx 는 즉시 fail (포맷/인증 문제, 재시도 무의미).
4. **timeout** — 1000+ row xlsx 는 import 에 30~60초 소요. timeout 최소 120초 설정.
5. **logging** — 응답 전체를 로그 파일에 저장 (errors/alerts 추적용).

---

## 6. 데이터 정합성 보장

- **멱등성**: `(entity_id, sales_date, document_no, row_number, product_name)` 5개 컬럼 unique constraint. 동일 데이터는 항상 무시 (`duplicates` 카운트만 증가).
- **트랜잭션**: 1 파일 = 1 DB transaction. 일부 row 만 실패하면 그 row 만 errors 에 기록되고 나머지는 정상 적재.
- **timezone**: 모든 날짜는 KST 기준. xlsx 의 datetime 셀은 그대로 사용.
- **VAT**: 매출 합계금액은 VAT 포함 base. 공급가액 (col O) 도 raw_data 에 보존 — 향후 K-GAAP 정합 view 에서 사용 가능.

---

## 7. 에러 처리

### 흔한 에러

| 에러 메시지 | 원인 | 해결 |
|---|---|---|
| `400: xlsx/xls 만 지원합니다` | csv / pdf 등 다른 포맷 | 파일 확장자 확인 |
| `400: 빈 파일입니다` | 0 byte 또는 손상 | 파일 무결성 확인 |
| `400: 파일 파싱 실패: ...` | xlsx 양식 다름 (col 위치 다름) | 매출관리 양식 확인 |
| `400: 파싱된 매출 row 가 없습니다` | col 7 (매출구분) 이 "매출" 인 row 없음 | 데이터 sheet 확인 |
| `401: Invalid or missing X-API-Key header` | 인증 활성화됐는데 헤더 없거나 틀림 | env 와 헤더 일치 확인 |
| `500: import 실패: ...` | DB 연결 / 스키마 오류 | 서버 로그 확인 후 운영자 문의 |

### errors 배열

응답의 `errors` 배열은 row 단위 실패 (전체 import 는 성공한 경우 일부 row 만 실패한 케이스). 최대 10개까지 노출.

```json
{
  "errors": [
    "row date=2026-04-01 payee=...: integer out of range"
  ]
}
```

---

## 8. 운영 정보

- **rate limit**: 현재 없음. 향후 IP 당 분당 60회로 제한 검토.
- **payload 크기 제한**: 10MB. 1000~2000 row 매출 xlsx 통상 ~500KB.
- **응답 시간**: 평균 5~20초 (1000 row 기준). DB write + alert 계산 포함.
- **시간 단위 주기 권장**: 일 1회 (매일 오전). 시간당 호출은 DB 부하 증가 — 필요 시 incremental 적재 protocol 별도 협의.

---

## 9. 변경 이력

| 날짜 | 변경 |
|---|---|
| 2026-05-07 | 초기 문서 작성. wholesale-sales / wholesale-purchases endpoint 노출. alerts 필드 추가 (cogs_book_vs_real_diff, negative_margin, missing_cogs) |
| 2026-05-07 | §1 인증 섹션 보강 — API key 생성 (openssl/PowerShell/Python), Vercel 설정 (Dashboard + CLI), 외부 프로그램 전달 권장/금지, 회전 절차, 보안 체크리스트 |

---

## 10. 문의

- 운영 팀: shawn@hanah1.com
- repo: https://github.com/shawnha/financeOne
- 신규 entity 추가, 양식 변경 등은 issue 등록.
