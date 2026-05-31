# HOI 매핑 적용 내용을 사람이 검토할 수 있는 HTML 리포트로 생성 (dry-run, rollback)
"""scripts/hoi_apply_mapping.py 가 --apply 시 무엇을 바꿀지 HTML 로 시각화.

DB 에 실제 쓰지 않음 (트랜잭션 후 rollback). docs/hoi_mapping_review.html 생성.
"""
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import html
import psycopg2

# apply 스크립트의 규칙을 그대로 재사용 (단일 진실 소스)
from scripts.hoi_apply_mapping import IA_STD_LINKS, RULES, HOLD, LEARN, match, load_dburl


def main():
    conn = psycopg2.connect(load_dburl())
    cur = conn.cursor()
    cur.execute("SET search_path TO financeone, public;")

    # 내부계정 / 표준계정 이름 lookup
    cur.execute("SELECT id, name FROM internal_accounts WHERE entity_id=1")
    ia_name = {r[0]: r[1] for r in cur.fetchall()}
    cur.execute("SELECT id, code, name, gaap_type FROM standard_accounts")
    sa = {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}
    cur.execute("SELECT code, id FROM standard_accounts WHERE gaap_type='US_GAAP'")
    code_to_id = {r[0]: r[1] for r in cur.fetchall()}

    # STEP 1 데이터: 내부계정 old→new std
    step1 = []
    for ia_id, std_code, note in IA_STD_LINKS:
        cur.execute("SELECT standard_account_id FROM internal_accounts WHERE id=%s", [ia_id])
        old = cur.fetchone()[0]
        new_id = code_to_id.get(std_code)
        old_disp = f"{sa[old][0]} {sa[old][1]} ({sa[old][2]})" if old in sa else "NULL (미연결)"
        new_disp = f"{sa[new_id][0]} {sa[new_id][1]}" if new_id in sa else std_code
        step1.append((ia_id, ia_name.get(ia_id, "?"), old_disp, new_disp, note))

    # STEP 2 데이터: 미분류 거래 매핑 제안
    cur.execute("""
        SELECT id, date, type, amount, COALESCE(counterparty,'')
        FROM transactions
        WHERE entity_id=1 AND internal_account_id IS NULL AND (is_cancel IS NOT TRUE)
        ORDER BY ABS(amount) DESC
    """)
    rows = cur.fetchall()
    mapped_rows, hold_rows = [], []
    for tid, date, ttype, amount, cp in rows:
        m = match(cp, ttype)
        if m:
            ia_id, label = m
            std_code = next((c for i, c, n in IA_STD_LINKS if i == ia_id), None)
            std_disp = ""
            if std_code and code_to_id.get(std_code) in sa:
                s = sa[code_to_id[std_code]]; std_disp = f"{s[0]} {s[1]}"
            else:
                cur.execute("SELECT standard_account_id FROM internal_accounts WHERE id=%s", [ia_id])
                cs = cur.fetchone()[0]
                std_disp = f"{sa[cs][0]} {sa[cs][1]}" if cs in sa else "(기존)"
            mapped_rows.append((str(date)[:10], ttype, float(amount), cp, label, std_disp))
        else:
            reason = next((h for h in HOLD if h in cp.lower()), "?")
            hold_rows.append((str(date)[:10], ttype, float(amount), cp, reason))

    conn.rollback()
    conn.close()

    # ── HTML 생성 ──
    def esc(s): return html.escape(str(s))
    def won(x): return f"${x:,.2f}"

    from collections import Counter
    label_cnt = Counter(r[4] for r in mapped_rows)
    total_mapped_amt = sum(abs(r[2]) for r in mapped_rows)
    total_hold_amt = sum(abs(r[2]) for r in hold_rows)

    rows_html = []
    for d, tp, amt, cp, label, std in sorted(mapped_rows, key=lambda x: -abs(x[2])):
        tcls = "inflow" if tp == "in" else "outflow"
        rows_html.append(
            f"<tr><td>{esc(d)}</td><td class='{tcls}'>{esc(tp)}</td>"
            f"<td class='num'>{won(abs(amt))}</td><td>{esc(cp)}</td>"
            f"<td class='ia'>{esc(label)}</td><td class='std'>{esc(std)}</td></tr>"
        )
    hold_html = []
    reason_label = {
        "hanah one korea": "매입대금 vs 차입금 — 2026 HOK원장 확인 대기",
        "nest grid": "정체 불명 입금 — 확인 대기",
        "ca dept tax": "CA 판매세 — sales tax 처리 방식 불명",
        "mercury credit": "카드대금(IO AUTOPAY) — 처리 검토",
    }
    for d, tp, amt, cp, reason in sorted(hold_rows, key=lambda x: -abs(x[2])):
        hold_html.append(
            f"<tr><td>{esc(d)}</td><td>{esc(tp)}</td><td class='num'>{won(abs(amt))}</td>"
            f"<td>{esc(cp)}</td><td class='reason'>{esc(reason_label.get(reason, reason))}</td></tr>"
        )
    step1_html = []
    for ia_id, nm, old, new, note in step1:
        relink = "relink" if "relink" in note else "신규"
        step1_html.append(
            f"<tr><td>{ia_id}</td><td class='ia'>{esc(nm)}</td>"
            f"<td class='old'>{esc(old)}</td><td class='arrow'>→</td>"
            f"<td class='std'>{esc(new)}</td><td><span class='badge {relink}'>{relink}</span></td></tr>"
        )
    cat_html = []
    for label, n in label_cnt.most_common():
        cat_html.append(f"<tr><td class='ia'>{esc(label)}</td><td class='num'>{n}건</td></tr>")
    learn_html = []
    for cp_pattern, ia_id in LEARN:
        learn_html.append(f"<tr><td>{esc(cp_pattern)}</td><td class='ia'>{esc(ia_name.get(ia_id,'?'))}</td></tr>")

    doc = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<title>HOI 거래 매핑 검토 — dry-run</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, 'Segoe UI', sans-serif; margin: 0; background: #0f1117; color: #e4e7ec; padding: 32px; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  h2 {{ font-size: 16px; margin: 32px 0 12px; color: #93c5fd; border-bottom: 1px solid #2a2f3a; padding-bottom: 6px; }}
  .sub {{ color: #98a2b3; font-size: 13px; margin-bottom: 24px; }}
  .cards {{ display: flex; gap: 12px; flex-wrap: wrap; }}
  .card {{ background: #1a1d27; border: 1px solid #2a2f3a; border-radius: 10px; padding: 16px 20px; min-width: 150px; }}
  .card .big {{ font-size: 26px; font-weight: 700; }}
  .card .lbl {{ font-size: 12px; color: #98a2b3; margin-top: 4px; }}
  .ok {{ color: #4ade80; }} .warn {{ color: #fbbf24; }} .info {{ color: #60a5fa; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 8px; }}
  th {{ text-align: left; padding: 8px 10px; background: #1a1d27; color: #98a2b3; font-weight: 600; position: sticky; top: 0; }}
  td {{ padding: 7px 10px; border-bottom: 1px solid #20242e; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }}
  .ia {{ color: #fcd34d; }} .std {{ color: #86efac; }} .old {{ color: #f87171; text-decoration: line-through; opacity: .7; }}
  .arrow {{ color: #60a5fa; text-align: center; }}
  .inflow {{ color: #4ade80; }} .outflow {{ color: #fb923c; }}
  .reason {{ color: #fbbf24; font-size: 12px; }}
  .badge {{ font-size: 11px; padding: 2px 8px; border-radius: 6px; }}
  .badge.relink {{ background: #422006; color: #fbbf24; }}
  .badge.신규 {{ background: #052e16; color: #4ade80; }}
  .scroll {{ max-height: 520px; overflow-y: auto; border: 1px solid #2a2f3a; border-radius: 8px; }}
  .note {{ background: #1a1d27; border-left: 3px solid #fbbf24; padding: 12px 16px; border-radius: 6px; font-size: 13px; margin: 12px 0; }}
</style></head><body>
<h1>HOI(entity=1) 거래 매핑 검토 — DRY-RUN</h1>
<div class="sub">QBO(US GAAP 정본) + HOI 2025 P&amp;L + cross-check 기반 · DB 미반영(rollback) · 생성: scripts/hoi_mapping_review_html.py</div>

<div class="cards">
  <div class="card"><div class="big ok">{len(mapped_rows)}</div><div class="lbl">매핑 거래</div></div>
  <div class="card"><div class="big info">{won(total_mapped_amt)}</div><div class="lbl">매핑 금액</div></div>
  <div class="card"><div class="big info">{len(step1)}</div><div class="lbl">표준계정 연결/relink</div></div>
  <div class="card"><div class="big warn">{len(hold_rows)}</div><div class="lbl">보류 (확인 대기)</div></div>
  <div class="card"><div class="big warn">{won(total_hold_amt)}</div><div class="lbl">보류 금액</div></div>
  <div class="card"><div class="big info">{len(LEARN)}</div><div class="lbl">학습 규칙</div></div>
</div>

<div class="note">⚠️ <b>표준계정 정책</b>: 내부계정은 한국식 유지, 표준계정은 QBO/US GAAP(HOI-PL-*) 기준 — 사장님 결정. relink = 기존 K_GAAP 표준계정을 US GAAP 으로 교체.</div>

<h2>STEP 1 — 내부계정 → US GAAP 표준계정 연결 ({len(step1)}개)</h2>
<table>
<tr><th>IA id</th><th>내부계정(한국식)</th><th>기존 표준계정</th><th></th><th>새 표준계정(US GAAP)</th><th>구분</th></tr>
{''.join(step1_html)}
</table>

<h2>STEP 2 — 거래 매핑 카테고리별 ({len(mapped_rows)}건)</h2>
<table style="max-width:360px">{''.join(cat_html)}</table>

<h2>STEP 2 — 거래 매핑 상세 ({len(mapped_rows)}건)</h2>
<div class="scroll"><table>
<tr><th>일자</th><th>유형</th><th>금액</th><th>거래처</th><th>→ 내부계정</th><th>→ 표준계정(US GAAP)</th></tr>
{''.join(rows_html)}
</table></div>

<h2 class="warn">⏸ 보류 — 매핑 안 함 ({len(hold_rows)}건 / {won(total_hold_amt)})</h2>
<table>
<tr><th>일자</th><th>유형</th><th>금액</th><th>거래처</th><th>사유</th></tr>
{''.join(hold_html)}
</table>

<h2>STEP 3 — mapping_rules 학습 (향후 자동매핑, {len(LEARN)}개)</h2>
<table style="max-width:560px">
<tr><th>거래처 패턴</th><th>→ 내부계정</th></tr>
{''.join(learn_html)}
</table>

</body></html>"""

    os.makedirs("docs", exist_ok=True)
    out = "docs/hoi_mapping_review.html"
    open(out, "w", encoding="utf-8").write(doc)
    print(f"WROTE {out} ({len(doc)} bytes, mapped={len(mapped_rows)}, hold={len(hold_rows)})")


if __name__ == "__main__":
    main()
