# 거래 자동 매핑 + 학습 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** counterparty 기반 내부계정 자동 매핑 + 사용자 수정 학습 + 매핑룰 관리 페이지

**Architecture:** mapping_service.py에 자동 매핑(auto_map)과 학습(learn_rule) 함수를 만들고, upload.py와 transactions.py에서 호출. 매핑룰 관리는 accounts.py 라우터에 추가, 프론트는 /accounts/mapping-rules 페이지.

**Tech Stack:** FastAPI, psycopg2, Next.js, AccountCombobox (기존 컴포넌트 재사용)

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `backend/services/mapping_service.py` | auto_map_transaction(), learn_mapping_rule() |
| Create | `backend/tests/test_mapping_service.py` | 자동 매핑 + 학습 로직 테스트 |
| Create | `frontend/src/app/accounts/mapping-rules/page.tsx` | 매핑룰 관리 페이지 |
| Modify | `backend/routers/upload.py:130-147` | 거래 INSERT 후 auto_map 호출 |
| Modify | `backend/routers/transactions.py:119-167` | PATCH 핸들러에 learn 호출 |
| Modify | `backend/routers/accounts.py` | mapping-rules CRUD 엔드포인트 추가 |
| Modify | `frontend/src/components/sidebar.tsx:45-49` | "매핑 규칙" 메뉴 추가 |

---

### Task 1: mapping_service.py — 자동 매핑 함수

**Files:**
- Create: `backend/services/mapping_service.py`
- Test: `backend/tests/test_mapping_service.py`

- [ ] **Step 1: Write failing test for auto_map_transaction**

```python
# backend/tests/test_mapping_service.py
"""mapping_service 테스트 — auto_map + learn"""

import pytest
from unittest.mock import MagicMock


def _mock_cursor(fetchone_result=None):
    cur = MagicMock()
    cur.fetchone.return_value = fetchone_result
    return cur


class TestAutoMap:
    def test_returns_mapping_when_rule_exists(self):
        from backend.services.mapping_service import auto_map_transaction

        cur = _mock_cursor(fetchone_result=(10, 20, 0.9))
        result = auto_map_transaction(cur, entity_id=2, counterparty="OPENAI *CHATGPT SUBSCR")
        assert result == {"internal_account_id": 10, "standard_account_id": 20, "confidence": 0.9}

    def test_returns_none_when_no_rule(self):
        from backend.services.mapping_service import auto_map_transaction

        cur = _mock_cursor(fetchone_result=None)
        result = auto_map_transaction(cur, entity_id=2, counterparty="새로운거래처")
        assert result is None

    def test_returns_none_when_counterparty_is_none(self):
        from backend.services.mapping_service import auto_map_transaction

        cur = MagicMock()
        result = auto_map_transaction(cur, entity_id=2, counterparty=None)
        assert result is None
        cur.execute.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/test_mapping_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.mapping_service'`

- [ ] **Step 3: Implement auto_map_transaction**

```python
# backend/services/mapping_service.py
"""거래 ↔ 내부계정 매핑 서비스 — 자동 매핑 + 학습"""


def auto_map_transaction(cur, *, entity_id: int, counterparty: str | None) -> dict | None:
    """counterparty로 mapping_rules 정확 일치 조회. 매칭 시 dict 반환, 미매칭 시 None."""
    if not counterparty:
        return None

    cur.execute(
        """
        SELECT internal_account_id, standard_account_id, confidence
        FROM mapping_rules
        WHERE entity_id = %s AND counterparty_pattern = %s AND confidence >= 0.8
        ORDER BY confidence DESC, hit_count DESC
        LIMIT 1
        """,
        [entity_id, counterparty],
    )
    row = cur.fetchone()
    if not row:
        return None

    return {
        "internal_account_id": row[0],
        "standard_account_id": row[1],
        "confidence": float(row[2]),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/test_mapping_service.py::TestAutoMap -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/services/mapping_service.py backend/tests/test_mapping_service.py
git commit -m "feat: auto_map_transaction 함수 + 테스트"
```

---

### Task 2: mapping_service.py — 학습 함수

**Files:**
- Modify: `backend/services/mapping_service.py`
- Modify: `backend/tests/test_mapping_service.py`

- [ ] **Step 1: Write failing test for learn_mapping_rule**

Append to `backend/tests/test_mapping_service.py`:

```python
class TestLearnRule:
    def test_inserts_new_rule(self):
        from backend.services.mapping_service import learn_mapping_rule

        cur = MagicMock()
        # No existing rule
        cur.fetchone.side_effect = [
            None,        # existing rule lookup
            (100,),      # standard_account_id from internal_accounts
        ]

        learn_mapping_rule(cur, entity_id=2, counterparty="OPENAI *CHATGPT SUBSCR", internal_account_id=10)

        # Should INSERT new rule
        calls = [str(c) for c in cur.execute.call_args_list]
        assert any("INSERT INTO mapping_rules" in c for c in calls)

    def test_updates_existing_same_account(self):
        from backend.services.mapping_service import learn_mapping_rule

        cur = MagicMock()
        # Existing rule with same internal_account_id
        cur.fetchone.return_value = (1, 10, 0.85, 3)  # id, internal_account_id, confidence, hit_count

        learn_mapping_rule(cur, entity_id=2, counterparty="OPENAI *CHATGPT SUBSCR", internal_account_id=10)

        calls = [str(c) for c in cur.execute.call_args_list]
        assert any("hit_count" in c and "UPDATE" in c for c in calls)

    def test_replaces_existing_different_account(self):
        from backend.services.mapping_service import learn_mapping_rule

        cur = MagicMock()
        # Existing rule with different internal_account_id
        cur.fetchone.side_effect = [
            (1, 99, 0.9, 5),  # existing rule points to account 99
            (200,),            # standard_account_id for new internal_account 10
        ]

        learn_mapping_rule(cur, entity_id=2, counterparty="OPENAI *CHATGPT SUBSCR", internal_account_id=10)

        calls = [str(c) for c in cur.execute.call_args_list]
        assert any("internal_account_id" in c and "UPDATE" in c for c in calls)

    def test_skips_when_counterparty_is_none(self):
        from backend.services.mapping_service import learn_mapping_rule

        cur = MagicMock()
        learn_mapping_rule(cur, entity_id=2, counterparty=None, internal_account_id=10)
        cur.execute.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/test_mapping_service.py::TestLearnRule -v`
Expected: FAIL — `ImportError: cannot import name 'learn_mapping_rule'`

- [ ] **Step 3: Implement learn_mapping_rule**

Append to `backend/services/mapping_service.py`:

```python
def learn_mapping_rule(cur, *, entity_id: int, counterparty: str | None, internal_account_id: int) -> None:
    """사용자의 계정 선택을 mapping_rules에 UPSERT."""
    if not counterparty:
        return

    # 기존 룰 조회
    cur.execute(
        """
        SELECT id, internal_account_id, confidence, hit_count
        FROM mapping_rules
        WHERE entity_id = %s AND counterparty_pattern = %s
        LIMIT 1
        """,
        [entity_id, counterparty],
    )
    existing = cur.fetchone()

    if existing:
        rule_id, existing_account_id, confidence, hit_count = existing
        if existing_account_id == internal_account_id:
            # 같은 계정 → hit_count 증가, confidence 상승
            new_confidence = min(1.0, float(confidence) + 0.05)
            cur.execute(
                "UPDATE mapping_rules SET hit_count = %s, confidence = %s, updated_at = NOW() WHERE id = %s",
                [hit_count + 1, new_confidence, rule_id],
            )
        else:
            # 다른 계정 → 교체
            cur.execute(
                "SELECT standard_account_id FROM internal_accounts WHERE id = %s",
                [internal_account_id],
            )
            std_row = cur.fetchone()
            std_id = std_row[0] if std_row else None

            cur.execute(
                """
                UPDATE mapping_rules
                SET internal_account_id = %s, standard_account_id = %s,
                    confidence = 0.8, hit_count = 1, updated_at = NOW()
                WHERE id = %s
                """,
                [internal_account_id, std_id, rule_id],
            )
    else:
        # 새 룰 생성
        cur.execute(
            "SELECT standard_account_id FROM internal_accounts WHERE id = %s",
            [internal_account_id],
        )
        std_row = cur.fetchone()
        std_id = std_row[0] if std_row else None

        cur.execute(
            """
            INSERT INTO mapping_rules (entity_id, counterparty_pattern, internal_account_id, standard_account_id, confidence, hit_count)
            VALUES (%s, %s, %s, %s, 0.8, 1)
            """,
            [entity_id, counterparty, internal_account_id, std_id],
        )
```

- [ ] **Step 4: Run all mapping_service tests**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/test_mapping_service.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/services/mapping_service.py backend/tests/test_mapping_service.py
git commit -m "feat: learn_mapping_rule 학습 함수 + 테스트"
```

---

### Task 3: upload.py — 업로드 시 자동 매핑 적용

**Files:**
- Modify: `backend/routers/upload.py:130-147`

- [ ] **Step 1: Add auto_map call after transaction INSERT**

In `backend/routers/upload.py`, add import at top:

```python
from backend.services.mapping_service import auto_map_transaction
```

After line 147 (`inserted_count += 1`), add:

```python
            # 자동 매핑: mapping_rules에서 counterparty 조회
            mapping = auto_map_transaction(cur, entity_id=entity_id, counterparty=tx.counterparty)
            if mapping:
                cur.execute(
                    """
                    UPDATE transactions
                    SET internal_account_id = %s, standard_account_id = %s,
                        mapping_source = 'rule', mapping_confidence = %s
                    WHERE entity_id = %s AND file_id = %s AND date = %s
                      AND amount = %s AND counterparty = %s AND description = %s
                    ORDER BY id DESC LIMIT 1
                    """,
                    [
                        mapping["internal_account_id"],
                        mapping["standard_account_id"],
                        mapping["confidence"],
                        entity_id, file_id, tx.date, tx.amount, tx.counterparty, tx.description,
                    ],
                )
                auto_mapped_count += 1
```

Also add `auto_mapped_count = 0` alongside `inserted_count = 0` near the top of the function, and include it in the response `stats`:

```python
"auto_mapped": auto_mapped_count,
```

- [ ] **Step 2: Refactor rematch to use auto_map_transaction**

In the `rematch_file_transactions` function (line 468-510), replace the inline mapping_rules query with:

```python
        # 2. 계정 재매칭: mapping_service 사용
        cur.execute(
            """
            SELECT t.id, t.counterparty
            FROM transactions t
            WHERE t.file_id = %s AND t.internal_account_id IS NULL AND t.counterparty IS NOT NULL
            """,
            [file_id],
        )
        unmapped_rows = cur.fetchall()

        account_matched = 0
        for tx_id, counterparty in unmapped_rows:
            mapping = auto_map_transaction(cur, entity_id=entity_id, counterparty=counterparty)
            if mapping:
                cur.execute(
                    """
                    UPDATE transactions
                    SET internal_account_id = %s, standard_account_id = %s,
                        mapping_source = 'rule', mapping_confidence = %s
                    WHERE id = %s
                    """,
                    [mapping["internal_account_id"], mapping["standard_account_id"], mapping["confidence"], tx_id],
                )
                account_matched += 1
```

- [ ] **Step 3: Run backend to verify no import errors**

Run: `source .venv/bin/activate && python3 -c "from backend.routers.upload import router; print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add backend/routers/upload.py
git commit -m "feat: 업로드 시 자동 매핑 + rematch 리팩토링"
```

---

### Task 4: transactions.py — 수정 시 학습

**Files:**
- Modify: `backend/routers/transactions.py:119-167`

- [ ] **Step 1: Add learn call to PATCH handler**

In `backend/routers/transactions.py`, add import at top:

```python
from backend.services.mapping_service import learn_mapping_rule
```

In the `update_transaction` function, after `cur.execute(UPDATE ...)` and `row = cur.fetchone()` (around line 144), add learning logic before the journal entry creation:

```python
        # 매핑 학습: internal_account_id 변경 시 mapping_rules UPSERT
        if body.internal_account_id is not None:
            # 거래의 counterparty + entity_id 조회
            cur.execute("SELECT counterparty, entity_id FROM transactions WHERE id = %s", [tx_id])
            tx_info = cur.fetchone()
            if tx_info and tx_info[0]:
                learn_mapping_rule(
                    cur,
                    entity_id=tx_info[1],
                    counterparty=tx_info[0],
                    internal_account_id=body.internal_account_id,
                )

            # 내부계정의 표준계정도 자동 설정
            if body.standard_account_id is None:
                cur.execute(
                    "SELECT standard_account_id FROM internal_accounts WHERE id = %s",
                    [body.internal_account_id],
                )
                std_row = cur.fetchone()
                if std_row and std_row[0]:
                    cur.execute(
                        "UPDATE transactions SET standard_account_id = %s WHERE id = %s",
                        [std_row[0], tx_id],
                    )
```

- [ ] **Step 2: Run existing tests to verify no regressions**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/ -v`
Expected: All existing tests pass

- [ ] **Step 3: Commit**

```bash
git add backend/routers/transactions.py
git commit -m "feat: 거래 수정 시 mapping_rules 자동 학습"
```

---

### Task 5: accounts.py — 매핑룰 CRUD API

**Files:**
- Modify: `backend/routers/accounts.py`

- [ ] **Step 1: Add Pydantic models for mapping rules**

Append to the request models section in `backend/routers/accounts.py`:

```python
class MappingRuleUpdate(BaseModel):
    internal_account_id: Optional[int] = None
```

- [ ] **Step 2: Add GET /mapping-rules endpoint**

Append to `backend/routers/accounts.py`:

```python
# ---------------------------------------------------------------------------
# Mapping rules
# ---------------------------------------------------------------------------

@router.get("/mapping-rules")
def list_mapping_rules(
    entity_id: int,
    search: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    where = ["mr.entity_id = %s"]
    params: list = [entity_id]

    if search:
        where.append("mr.counterparty_pattern ILIKE %s")
        params.append(f"%{search}%")

    where_clause = " AND ".join(where)
    offset = (page - 1) * per_page

    cur.execute(f"SELECT COUNT(*) FROM mapping_rules mr WHERE {where_clause}", params)
    total = cur.fetchone()[0]

    cur.execute(
        f"""
        SELECT mr.id, mr.counterparty_pattern,
               mr.internal_account_id, ia.name AS internal_account_name, ia.code AS internal_account_code,
               mr.standard_account_id, sa.name AS standard_account_name, sa.code AS standard_account_code,
               mr.confidence, mr.hit_count, mr.updated_at
        FROM mapping_rules mr
        LEFT JOIN internal_accounts ia ON mr.internal_account_id = ia.id
        LEFT JOIN standard_accounts sa ON mr.standard_account_id = sa.id
        WHERE {where_clause}
        ORDER BY mr.hit_count DESC, mr.updated_at DESC
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset],
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()

    return {"items": rows, "total": total, "page": page, "per_page": per_page}
```

- [ ] **Step 3: Add PATCH /mapping-rules/{id} endpoint**

```python
@router.patch("/mapping-rules/{rule_id}")
def update_mapping_rule(
    rule_id: int,
    body: MappingRuleUpdate,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")

    if body.internal_account_id is not None:
        # 내부계정의 표준계정 자동 조회
        cur.execute("SELECT standard_account_id FROM internal_accounts WHERE id = %s", [body.internal_account_id])
        std_row = cur.fetchone()
        std_id = std_row[0] if std_row else None

        cur.execute(
            """
            UPDATE mapping_rules
            SET internal_account_id = %s, standard_account_id = %s, updated_at = NOW()
            WHERE id = %s RETURNING id
            """,
            [body.internal_account_id, std_id, rule_id],
        )
    else:
        raise HTTPException(400, "No fields to update")

    if not cur.fetchone():
        raise HTTPException(404, "Mapping rule not found")

    conn.commit()
    cur.close()
    return {"id": rule_id, "updated": True}
```

- [ ] **Step 4: Add DELETE /mapping-rules/{id} endpoint**

```python
@router.delete("/mapping-rules/{rule_id}")
def delete_mapping_rule(
    rule_id: int,
    conn: PgConnection = Depends(get_db),
):
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public")
    cur.execute("DELETE FROM mapping_rules WHERE id = %s RETURNING id", [rule_id])
    if not cur.fetchone():
        raise HTTPException(404, "Mapping rule not found")
    conn.commit()
    cur.close()
    return {"id": rule_id, "deleted": True}
```

- [ ] **Step 5: Verify API starts cleanly**

Run: `source .venv/bin/activate && python3 -c "from backend.routers.accounts import router; print('OK')"`
Expected: OK

- [ ] **Step 6: Commit**

```bash
git add backend/routers/accounts.py
git commit -m "feat: 매핑룰 CRUD API (GET/PATCH/DELETE)"
```

---

### Task 6: sidebar.tsx — 매핑 규칙 메뉴 추가

**Files:**
- Modify: `frontend/src/components/sidebar.tsx:44-50`

- [ ] **Step 1: Add Link icon import and menu item**

In `sidebar.tsx`, add `Link2` to the lucide-react import:

```typescript
import {
  LayoutDashboard,
  TrendingUp,
  CreditCard,
  Upload,
  MessageSquare,
  Settings,
  FileText,
  BarChart3,
  Users,
  BookOpen,
  Menu,
  X,
  ArrowLeftRight,
  DollarSign,
  Link2,
} from "lucide-react"
```

Add the "매핑 규칙" menu item in the "계정" section (after "표준 계정"):

```typescript
  {
    label: "계정",
    items: [
      { label: "내부 계정", icon: BookOpen, href: "/accounts/internal", enabled: true },
      { label: "표준 계정", icon: BookOpen, href: "/accounts/standard", enabled: true },
      { label: "매핑 규칙", icon: Link2, href: "/accounts/mapping-rules", enabled: true },
    ],
  },
```

- [ ] **Step 2: Verify frontend builds**

Run: `cd frontend && npx next build --no-lint 2>&1 | tail -5`
Expected: No errors (the page doesn't exist yet, but sidebar link is fine)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/sidebar.tsx
git commit -m "feat: 사이드바에 매핑 규칙 메뉴 추가"
```

---

### Task 7: 매핑룰 관리 페이지 (프론트엔드)

**Files:**
- Create: `frontend/src/app/accounts/mapping-rules/page.tsx`

- [ ] **Step 1: Create mapping-rules page**

```tsx
// frontend/src/app/accounts/mapping-rules/page.tsx
"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useSearchParams } from "next/navigation"
import { fetchAPI } from "@/lib/api"
import { AccountCombobox } from "@/components/account-combobox"
import { cn } from "@/lib/utils"
import { EntityTabs } from "@/components/entity-tabs"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel,
  AlertDialogContent, AlertDialogDescription, AlertDialogFooter,
  AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Trash2, Search, Link2 } from "lucide-react"

type MappingRule = {
  id: number
  counterparty_pattern: string
  internal_account_id: number | null
  internal_account_name: string | null
  internal_account_code: string | null
  standard_account_id: number | null
  standard_account_name: string | null
  standard_account_code: string | null
  confidence: number
  hit_count: number
  updated_at: string
}

type InternalAccount = {
  id: number
  code: string
  name: string
  parent_id: number | null
  parent_name: string | null
}

export default function MappingRulesPage() {
  const searchParams = useSearchParams()
  const entityId = searchParams.get("entity") || "2"

  const [rules, setRules] = useState<MappingRule[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [internalAccounts, setInternalAccounts] = useState<InternalAccount[]>([])
  const [editingId, setEditingId] = useState<number | null>(null)

  const perPage = 50

  const fetchRules = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ entity_id: entityId, page: String(page), per_page: String(perPage) })
      if (search) params.set("search", search)
      const data = await fetchAPI(`/accounts/mapping-rules?${params}`)
      setRules(data.items)
      setTotal(data.total)
    } catch (e) {
      setError(e instanceof Error ? e.message : "조회 실패")
    } finally {
      setLoading(false)
    }
  }, [entityId, page, search])

  const fetchAccounts = useCallback(async () => {
    try {
      const data = await fetchAPI(`/accounts/internal?entity_id=${entityId}`)
      setInternalAccounts(Array.isArray(data) ? data : data.items || [])
    } catch {}
  }, [entityId])

  useEffect(() => { fetchRules() }, [fetchRules])
  useEffect(() => { fetchAccounts() }, [fetchAccounts])
  useEffect(() => { setPage(1) }, [entityId, search])

  const handleUpdateAccount = useCallback(async (ruleId: number, internalAccountId: string) => {
    setEditingId(null)
    try {
      await fetchAPI(`/accounts/mapping-rules/${ruleId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ internal_account_id: Number(internalAccountId) }),
      })
      fetchRules()
    } catch {}
  }, [fetchRules])

  const handleDelete = useCallback(async (ruleId: number) => {
    try {
      await fetchAPI(`/accounts/mapping-rules/${ruleId}`, { method: "DELETE" })
      fetchRules()
    } catch {}
  }, [fetchRules])

  const totalPages = Math.ceil(total / perPage)

  return (
    <div className="space-y-6">
      <EntityTabs />

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">매핑 규칙</h1>
          <p className="text-sm text-muted-foreground mt-1">
            거래처 → 내부계정 자동 매핑 규칙 ({total}건)
          </p>
        </div>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center gap-3">
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="거래처 검색..."
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="pl-9"
              />
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-8 text-center text-muted-foreground">로딩 중...</div>
          ) : error ? (
            <div className="p-8 text-center text-destructive">{error}</div>
          ) : rules.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground">
              <Link2 className="h-8 w-8 mx-auto mb-3 opacity-40" />
              <p>매핑 규칙이 없습니다</p>
              <p className="text-xs mt-1">거래내역에서 계정을 선택하면 자동으로 학습됩니다</p>
            </div>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[300px]">거래처</TableHead>
                    <TableHead className="w-[200px]">내부계정</TableHead>
                    <TableHead className="w-[160px]">표준계정</TableHead>
                    <TableHead className="w-[80px] text-center">신뢰도</TableHead>
                    <TableHead className="w-[80px] text-center">적용</TableHead>
                    <TableHead className="w-[50px]" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rules.map(rule => (
                    <TableRow key={rule.id}>
                      <TableCell className="font-mono text-xs">{rule.counterparty_pattern}</TableCell>
                      <TableCell
                        className="cursor-pointer hover:bg-muted/20 transition-colors"
                        onClick={() => setEditingId(rule.id)}
                      >
                        {editingId === rule.id ? (
                          <AccountCombobox
                            options={internalAccounts}
                            value={rule.internal_account_id ? String(rule.internal_account_id) : ""}
                            onChange={v => handleUpdateAccount(rule.id, v)}
                            placeholder="선택..."
                            compact
                            autoOpen
                          />
                        ) : (
                          <span className={cn("text-xs", rule.internal_account_name ? "text-foreground" : "text-muted-foreground")}>
                            {rule.internal_account_name || "-"}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {rule.standard_account_name || "-"}
                      </TableCell>
                      <TableCell className="text-center">
                        <span className={cn(
                          "text-xs font-mono px-1.5 py-0.5 rounded",
                          rule.confidence >= 0.95 ? "bg-green-500/10 text-green-400" :
                          rule.confidence >= 0.8 ? "bg-yellow-500/10 text-yellow-400" :
                          "bg-red-500/10 text-red-400"
                        )}>
                          {(rule.confidence * 100).toFixed(0)}%
                        </span>
                      </TableCell>
                      <TableCell className="text-center text-xs text-muted-foreground">
                        {rule.hit_count}회
                      </TableCell>
                      <TableCell>
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive">
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>매핑 규칙 삭제</AlertDialogTitle>
                              <AlertDialogDescription>
                                &quot;{rule.counterparty_pattern}&quot; → {rule.internal_account_name} 규칙을 삭제하시겠습니까?
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>취소</AlertDialogCancel>
                              <AlertDialogAction onClick={() => handleDelete(rule.id)}>삭제</AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              {totalPages > 1 && (
                <div className="flex items-center justify-center gap-2 p-4 border-t">
                  <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>이전</Button>
                  <span className="text-xs text-muted-foreground">{page} / {totalPages}</span>
                  <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>다음</Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
```

- [ ] **Step 2: Verify frontend builds**

Run: `cd frontend && npx next build --no-lint 2>&1 | tail -5`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/accounts/mapping-rules/page.tsx
git commit -m "feat: 매핑룰 관리 페이지 (/accounts/mapping-rules)"
```

---

### Task 8: 통합 테스트 + 응답에 auto_mapped 포함

**Files:**
- Modify: `backend/tests/test_mapping_service.py`

- [ ] **Step 1: Add integration-style test**

Append to `backend/tests/test_mapping_service.py`:

```python
class TestAutoMapAndLearnFlow:
    """자동 매핑 → 학습 → 재매핑 전체 플로우 테스트"""

    def test_learn_then_auto_map(self):
        """학습 후 같은 거래처로 auto_map하면 매칭되어야 함"""
        from backend.services.mapping_service import auto_map_transaction, learn_mapping_rule

        # 1. 학습: "OPENAI" → internal_account 10
        learn_cur = MagicMock()
        learn_cur.fetchone.side_effect = [
            None,    # no existing rule
            (20,),   # standard_account_id for internal_account 10
        ]
        learn_mapping_rule(learn_cur, entity_id=2, counterparty="OPENAI *CHATGPT SUBSCR", internal_account_id=10)

        # INSERT가 호출되었는지 확인
        insert_calls = [c for c in learn_cur.execute.call_args_list if "INSERT INTO mapping_rules" in str(c)]
        assert len(insert_calls) == 1

        # 2. 자동 매핑: 같은 거래처로 조회
        map_cur = _mock_cursor(fetchone_result=(10, 20, 0.8))
        result = auto_map_transaction(map_cur, entity_id=2, counterparty="OPENAI *CHATGPT SUBSCR")
        assert result is not None
        assert result["internal_account_id"] == 10
```

- [ ] **Step 2: Run all tests**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/test_mapping_service.py -v`
Expected: 8 passed

- [ ] **Step 3: Run full test suite**

Run: `source .venv/bin/activate && python3 -m pytest backend/tests/ -v`
Expected: All tests pass (no regressions)

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_mapping_service.py
git commit -m "test: 자동 매핑 + 학습 통합 테스트"
```
