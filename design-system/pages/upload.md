# Upload Page Design

## Layout
- 상단: 법인 선택 탭 (HOI | 한아원코리아 | 한아원리테일)
- 메인: 드래그앤드롭 업로드 영역 (센터)
- 하단: 최근 업로드 히스토리 테이블

## Upload Zone (2×2 Bento)

```
┌─────────────────────────────────────────┐
│                                         │
│      ☁ (Lucide: Upload icon, 48px)      │
│                                         │
│   Excel 파일을 드래그하거나 클릭하세요     │
│   .xls, .xlsx · 최대 10MB               │
│                                         │
│   [ 파일 선택 ]  (btn-secondary)         │
│                                         │
└─────────────────────────────────────────┘
```

- 배경: `--card` (#1E293B)
- 테두리: dashed 2px `--border` (#334155)
- 드래그 오버: 테두리 `--accent` (#22C55E) + 배경 `rgba(34,197,94,0.05)`
- 아이콘: Lucide `Upload`, 48px, `--muted-foreground`
- 텍스트: Body 14px `--foreground`, 부가 텍스트 12px `--muted-foreground`

## Source Type Auto-Detection

업로드 시 파일 내용으로 출처 자동 감지:
- 롯데카드 (.xls) → `lotte_card` 배지 (red)
- 우리카드 (.xls) → `woori_card` 배지 (blue)
- 우리은행 (.xlsx) → `woori_bank` 배지 (blue)
- 감지 실패 → 수동 선택 드롭다운

## Upload Progress

```
┌─────────────────────────────────────────┐
│  📄 우리은행_202501.xlsx                  │
│  ┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫ 100% │
│  ✓ 461건 파싱 완료 · 체크카드 중복 18건   │
│  [ 거래내역 보기 ]  (btn-primary)         │
└─────────────────────────────────────────┘
```

- 프로그레스 바: height 4px, `--accent` (#22C55E)
- 파싱 결과: 건수 (green), 중복 건수 (yellow `--warning`)
- 스킵된 행: 경고 아이콘 + 줄 번호 리스트 (접힘/펼침)

## Upload History (4×1 Full-width Table)

| # | Column | Width | Notes |
|---|--------|-------|-------|
| 1 | 업로드일 | 120px | YYYY-MM-DD HH:mm |
| 2 | 파일명 | flex | 원본 파일명 |
| 3 | 출처 | 90px | source_type 배지 |
| 4 | 법인 | 100px | entity name |
| 5 | 건수 | 80px | 파싱된 거래 수, right-aligned, mono |
| 6 | 중복 | 80px | 중복 감지 수, warning color if > 0 |
| 7 | 상태 | 100px | 완료(green) / 부분(yellow) / 실패(red) |

## Error Handling

- 파일 형식 에러: "지원하지 않는 파일 형식입니다. .xls 또는 .xlsx 파일만 업로드 가능합니다."
- 파일 크기 에러: "파일 크기가 10MB를 초과합니다. 더 작은 파일을 업로드해주세요."
- 중복 업로드 경고: "같은 파일명의 데이터가 이미 존재합니다. 덮어쓰시겠습니까?" → 확인/취소 모달
- 부분 파싱: "총 500행 중 461행 파싱 성공. 39행 스킵됨." → 스킵 상세 보기 링크
- DB 연결 실패: exponential backoff 후 "서버 연결이 지연되고 있습니다. 잠시 후 다시 시도해주세요."

## Interaction States

| State | Implementation |
|-------|----------------|
| LOADING | 없음 (즉시 표시) |
| EMPTY | 드래그앤드롭 영역 + "첫 데이터를 업로드해보세요!" |
| ERROR | 에러 메시지 (위 참조) + 재업로드 안내 |
| SUCCESS | "N건 업로드 완료" 성공 배너 (auto-dismiss 5초) + 거래내역 보기 버튼 |
| PARTIAL | 경고 배너 + 스킵된 행 상세 + 성공 건수 표시 |

## Multiple File Upload
- 여러 파일 동시 드래그 가능
- 각 파일별 개별 프로그레스 + 결과
- 전체 요약: "3개 파일, 총 1,234건 업로드 완료"
