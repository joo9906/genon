# WIP — 006 업로드 문서 자동 채움을 **대화 중간에도** (2026-09-02 착수)

> **이 파일은 진행 기록이다.** 세션이 초기화되면 여기부터 읽는다.
> 완료되면 내용을 루트 `CLAUDE.md` 로 옮기고 이 파일을 지운다.
>
> **갱신 규칙**: 아래 §3 체크리스트를 한 항목 끝낼 때마다 즉시 고친다.
> 코드를 고치고 이 파일을 안 고치면 다음 세션이 같은 자리를 다시 판다.

---

## 1. 요구 (2026-09-02, 사용자 확정)

지금은 업로드 문서 자동 채움이 **첫 턴에만** 돈다. 바뀐 요구는 셋이다.

1. **대화 중간에도 파일을 올릴 수 있다.** 채팅 시작 시점으로 제한하지 않는다.
2. **이미 채운 내용을 밀어버리지 않는다.** 남아 있는 중괄호(=아직 빈 항목)만 그 파일로
   채운다.
3. **파일이 여러 번 들어올 수 있다.** 어느 문서를 이미 태웠는지를 **Redis 세션에**
   들고 있는다 (그 세션에서만).

### 요구에서 바로 안 나오는 것 — 내가 정한 것

- **Redis 에 넣는 것은 문서 해시 목록이지 문서 본문이 아니다.** 본문을 세션에 넣으면
  §3.8(사용자 데이터를 남기지 않는다)을 어기고, 자동 채움은 그 턴에 끝나므로 뒤에서
  본문을 다시 볼 일이 없다. 지금도 `_doc_hash()` 16자만 저장한다.
- **목록에 상한을 둔다** (`_MAX_DOC_HASHES`). 없으면 긴 대화에서 세션 페이로드가
  단조 증가한다.

---

## 2. 착수 시점의 사실 (2026-09-02 확인)

**새 요구는 코드에 한 줄도 안 들어가 있었다.** 있는 것은 2026-08-31 판(첫 턴 전용)뿐.
`git log` 최근 커밋(`f2fc6f8`)까지 확인했고 브랜치·스택에도 선행분이 없다.

이미 되어 있어서 **안 고쳐도 되는 것** (다시 조사하지 말 것):

| 이미 된 것 | 어디 |
|---|---|
| 빈 항목만 채우고 기존 값을 절대 안 덮는다 (두 층) | `doc_prefill._pending_specs` + `conflicts` 카운터, 커밋의 `name not in state.values` |
| 워크플로우가 **매 턴** `genosUploaded` 를 보고 prefill 을 부른다 | `sfr006_01_context.py:357` — `if document:` 뿐이고 턴 번호를 안 본다 |
| 문서 값 → 발화 값 병합 순서 (발화가 이긴다) | `chat_api.chat_commit` — prefilled 먼저 merge |
| 조각 분할·앞 조각 우선·조기 종료 | `doc_prefill.split_document` / `prefill_from_document` |

**막고 있는 것은 서빙 쪽 게이트 하나다** — `chat_api.py` 의

```python
if state.values or state.blocks:
    return _prefill_skipped("already_started", ...)
```

이 줄이 "대화가 시작됐으면 안 돈다" 이고, 요구 2 를 다른 층(`_pending_specs`)이 이미
보장하므로 **이 게이트는 지금 요구에서 불필요하다.**

---

## 3. 체크리스트 (진행 상황 — **여기를 갱신한다**)

- [x] **1. `session_store.py`** — `source_doc_hash: str` → `source_doc_hashes: list`
  - [x] `load_session` 기본값 `[]`, 옛 문자열 세션 흡수(버리지 않는다), 타입 정규화
  - [x] `save_session(source_doc_hashes=...)`, 상한 `_MAX_DOC_HASHES`(20), `_STATE_VERSION` 2→3
- [x] **2. `chat_api.py`**
  - [x] `already_started` 스킵 제거
  - [x] `already_applied` 판정을 목록 멤버십으로
  - [x] 빈 항목이 0개면 `no_pending_fields` 로 스킵 (LLM 을 안 부른다)
  - [x] 커밋에서 해시 **누적 병합**(`_merged_doc_hashes`) — 덮어쓰기가 아니다
- [x] **3. 안내문·스텝 배선**
  - [x] `chat_reply._prefill_notices` — "첫 턴에만" 전제 제거, `no_pending_fields` 한 줄
  - [x] `sfr006_01_context.py` — `prefill_skipped_reason` 을 data 로 흘린다
  - [x] `sfr006_03_commit.py` — 커밋에 넘긴다
- [x] **덤: `session_view.py` 의 기존 결함** (아래 §4-1)
- [x] **4. 그물** — 전부 돌려서 통과 확인
  - [x] `SFR-006/tests/test_doc_prefill.py` +2 · `test_session_store.py` +4 → **48 → 54건**
  - [x] `onprem/test/check_chat_turn.py` +7 → **34 → 41건**
  - [x] `onprem/test/check_api_contract.py` +1 → **45 → 46건**
  - [x] **다섯 갈래를 되돌려 FAIL 확인** (§5)
- [x] **5. 문서**
  - [x] 루트 `CLAUDE.md` — "중간에 올려도 남은 자리만" 절 신규 + 검증 건수표
  - [x] `onprem/codeserving/SFR-006_template_fill/CLAUDE.md`
  - [x] `onprem/docs/FRONT.md` (프론트 계약 — "매 턴 실어 보내도 된다")
  - [x] `onprem/WORK.MD` 줄 수 7개 + 09-02 대조표 + 합계 재계수

**§3 은 끝났다.** 남은 것은 §6 의 SFR-006-03-02 뿐이다.

---

## 4. 설계 판단 (구현하며 정한 것 — 되돌리지 말 것)

- **`no_pending_fields` 도 해시를 기록한다.** 안 하면 캔버스가 같은 문서를 매 턴 실어
  올 때마다 같은 안내문이 반복된다. 대가는 "항목을 다 채운 뒤 올린 문서는, 나중에
  항목을 지워도 자동으로 안 채워진다" 인데 그때는 대화로 말하는 쪽이 빠르다.
- **판정 순서는 `disabled → no_document → already_applied → no_pending_fields`.**
  `already_applied` 가 앞이라야 같은 문서에서 안내문이 한 번만 나간다.
- **`state.blocks` 는 더 이상 게이트가 아니다.** 본문 블록이 있다는 것은 "대화가
  진행됐다" 는 뜻일 뿐이고, 빈 항목이 남아 있으면 채우는 것이 요구다.
- **경계를 건너는 것은 이번 턴 해시 하나**(`source_doc_hash`)이고 목록은 세션에만 있다.
  스텝이 목록을 들고 다니면 그것이 곧 세션 사본이 되고 두 벌이 갈린다.
- **"무엇이 부족한가" 판정을 하나로 모았다.** `doc_prefill._pending_specs` 가
  `missing_field_names` 를 쓴다 — 같은 조건이 두 곳에 있으면 "채울 자리가 없다며
  건너뛰는데 정작 빈 항목이 남은" 상태가 생긴다.

### 4-1. 같이 고친 **기존 결함** (이 요구가 없었어도 결함이었다)

`session_view.save_state`(화면 직접 편집 — `PATCH/DELETE /values`·`PUT /blocks`)가
`save_session` 에 **표식을 안 넘기고 있었다.** 세션 저장이 키 하나 덮어쓰기라 그 순간
표식이 지워지고, **다음 대화 턴에 업로드 문서가 통째로 다시 태워진다** — 사용자가 방금
화면에서 지운 값이 되살아나는 것으로 보이고 오류는 나지 않는다. `EditingContext` 가
표식을 들고 다니게 했다(`blocks` 를 함께 넘기는 이유와 같다).

**그물이 0건이던 자리다** — 되돌려 봤더니 아무 점검도 안 물었다. `check_api_contract` 에
1건을 넣고 다시 되돌려 FAIL 을 확인했다.

---

## 5. 검증

```bash
export PYTHONIOENCODING=utf-8
cd SFR-006 && python -m unittest discover -s tests -t .   # 48 → 54건
python onprem/test/check_chat_turn.py                     # 34 → 41건
python onprem/test/check_api_contract.py                  # 45 → 46건
python onprem/test/check_workflow_run.py                  # 91건 (변동 없음)
python onprem/test/check_deploy_contract.py               # FAIL 0 / WARN 3 / OK 63 (변동 없음)
```

**2026-09-02 실측 — 전부 통과**: SFR-006 unittest **54 OK** · `check_chat_turn` **41/41** ·
`check_api_contract` **46/46** · `check_workflow_run` **91/91** ·
`check_deploy_contract` **63 OK / WARN 3**.

**되돌려 FAIL 을 확인한 갈래 다섯** (전부 실제로 되돌려 돌려 봤다):

| 되돌린 것 | 무는 판정 |
|---|---|
| `already_started` 게이트 되살리기 | 중간 업로드 3건 동시 FAIL |
| 해시 누적 → 덮어쓰기 | "문서 표식이 누적된다" |
| `no_pending_fields` 게이트 제거 | "채울 자리가 없다는 사실을 답변이 말한다" |
| 옛 세션(문자열) 흡수 제거 | `test_legacy_single_hash_is_absorbed` |
| 화면 편집이 표식을 안 싣는다 | "PATCH /values 가 표식을 지우지 않는다" |

> **세 번째는 처음에 예상과 다르게 물었다.** 게이트를 없애도 "LLM 호출 수" 판정은
> 통과한다 — `doc_prefill` 이 `pending` 이 비면 첫 조각에서 `break` 하기 때문이다
> (층이 둘이라는 증거다). 실제로 사라지는 것은 **안내문**이고 그쪽이 물었다.

---

## 6. 같이 접수된 다른 건 (2026-09-02 — **이 작업과 별개**)

출처는 요구사항 정의서
`genos_files/260826_CCRS-REQ-02-01(요구사항정의서-기능_비기능)_v.1.0.xlsx` 의 **기능** 시트다
(각각 127~128행 · 329행). 아래는 그 행의 **원문**이다.

### SFR-006-03-02 — **논의 중이라 보류** (2026-09-02 중단)

> **착수했다가 사용자 지시로 멈췄다. 코드는 한 줄도 안 건드렸다** — 현행 등록 경로
> (`template_store.py` · `main.py` 의 `POST /templates`)를 읽은 것이 전부다.
> **방향이 정해지기 전에 다시 손대지 말 것.** 아래 원문·현행 상태는 그때 다시 쓴다.

> **(버전 관리)** 신규 등록·수정 및 **템플릿 버전 관리(변경 이력 기록)** 를 **관리자 웹
> UI** 에서 수행 / "신규 등록·수정 및 템플릿 버전 관리(변경 이력 기록)할 수 있도록
> **관리자 기능**으로 제공"

**대화 중 값 수정 이력이 아니라 템플릿 파일의 판본 이력이다.** 착수할 때 헷갈리지 말 것 —
바로 위(SFR-006-03-01)가 템플릿 카테고리 분류이고 이 항목은 그 짝이다.

지금 상태 (착수 전 확인): `POST /templates` 는 볼륨의 hwpx 를 **덮어쓴다.** 판본도
이력도 남지 않아 **"누가 언제 무엇을 바꿨나" 를 답할 수 없고 되돌릴 수도 없다.**
관련 자리는 `template_store.py`(볼륨 I/O) · `main.py` 의 등록·삭제 라우트 ·
`template_index.py`(내용 해시로 캐시를 무효화하므로 **판본 식별에 쓸 값이 이미 있다**).

### SFR-018-02-03 — **보류** (플랫폼 **용어사전 API 가 나온 뒤**)

> 시스템은 **위원회 도메인 영어사전 기능**을 제공하여야 한다.
> [After / 26.07.30 미팅] "'영문 표준 번역어 필드'를 반드시 추가해야 하는 것은 아니며
> 이후 언어 확장성을 고려해 **용어명/정의/유의어/…/언어** 와 같은 형태로 제공해도 무관"
> [3차 검토의견 260822~23] "플랫폼은 **'도메인 영어사전 기능'을 제공**하고, 위원회는 동
> 기능을 통해 향후 지속적으로 '한-영 표기'를 관리한다"

**보류 근거는 우리 코드가 아니라 플랫폼 일정이다.** 지금 손대면 API 모양을 추측해 짜게
되고 그 사본은 API 가 나온 날 통째로 다시 쓴다.

**그때 고칠 자리는 이미 한 곳으로 좁혀져 있다** — 지금 우리는 플랫폼 용어사전에
번역어 칸이 없어서 `용어명 → 한국어`, `설명 → 영어` 로 읽는다(2026-08-14 사내 확정).
요구가 말하는 **'언어' 구분 필드**가 API 에 생기면 **적재부만** 바꾼다:
`common/glossary_store.py` 와 MCP `genon_glossary.py` **두 사본** (매칭·하이라이트·
준수율 코드는 안 바뀐다). 두 사본을 함께 고치지 않으면 워크플로우 경로와 직접 업로드
경로가 **다른 용어 목록**을 쓴다.
