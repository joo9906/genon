# SFR-006 — HWPX 템플릿 채우기 (보고서·공문 초안 생성)

> ⚠️ **이 디렉토리는 테스트 보유 사본이고, 현행 코드는 `onprem/SFR-006_template_fill/` 이다.**
> 2026-08-05 부터 현장 템플릿 방식인 **라벨 항목**(본문에 텍스트로 적힌
> `제목: {볼드체, 고딕, 16pt}`)과 서식 명세 적용·톤 적용·업로드 생성은 `onprem/` 쪽에만
> 있다. 여기 있는 `tests/` 는 누름틀·`{{token}}` 경로만 검증한다.

hwpx 템플릿의 **누름틀(CLICK_HERE 필드)** 을 기준으로, 사용자와 멀티턴 대화로
필요한 값을 수집하고, 다운로드 버튼을 누르면 초안 hwpx 를 생성해 준다.

## 구성

```
hwpx.py                  # (레거시) {{token}} 방식 로컬 검증 CLI — 반복 블록 복제 포함
template_fill/           # 프로덕션 패키지
  hwpx_fields.py         # ⭐ lxml 누름틀 파서/필러 + {{token}} 폴백 (양 영역 공유)
  run_chat.py            # 워크플로우 Python 단계 (area 02) — 멀티턴 값 수집
  main.py                # 코드 서빙 (area 03) — 다운로드 버튼용 /generate API
  session_store.py       # 턴 사이 수집 상태 보존 (파일 기반, 공유 볼륨)
  llm.py                 # Gateway LLM 호출 (LlmResult 패턴)
  prompts.py             # 필드 추출 프롬프트
  field_judge.py         # LLM 응답 검증 (화이트리스트) + mock 추출기
  config.py / error_codes.py / logging_utils.py
  tests/                 # 합성 hwpx 라운드트립 — LLM/GenOS 없이 실행 가능
```

## 동작 흐름

```
[대화 턴마다 — run_chat.run(data)]
  템플릿 스캔(누름틀 스키마) → 세션 상태 로드
  → LLM: 사용자 발화에서 {필드명: 값} 후보 추출 (역할 한정)
  → 코드: 화이트리스트 검증 → 세션 병합·저장 → 채워짐/부족 판정(결정적)
  → 채팅 응답: 반영 내역 + 작성 현황 표 + 다음 질문
  → result 이벤트: field_values / fields_missing / ready_for_download

[다운로드 버튼 — POST /generate]
  {template_id, session_id} → 세션 값 로드 → fill_template()
  → hwpx 바이너리 응답 (Content-Disposition, X-Missing-Fields 헤더)
```

책임 분리 원칙: **LLM 은 추출까지만, 채워짐/부족 판정은 코드가 한다.**
(LLM 응답 불신 — 저장소 CLAUDE.md §5)

## 판정 규칙 (누름틀)

- `fieldBegin(type=CLICK_HERE)` ~ `fieldEnd` 사이 텍스트가
  **비어 있지 않고 안내문(stringParam)과 다르면** 채워진 것으로 본다.
- begin/end 짝은 **문서 순서 스택 매칭** (문단 id 는 전부 중복이라 신뢰 불가).
- 값 기록: 사이 첫 `hp:t` 에 대입, 나머지는 비움. `hp:t` 가 없으면 begin run 을
  deepcopy 해 서식(charPrIDRef)을 보존한 채 새 run/t 삽입.
- 값이 없는 필드는 안내문 상태로 남긴다 (부분 초안 → 한/글에서 이어서 작성).

## GenOS 배포 체크리스트

1. **템플릿 등록**: 관리자가 hwpx 템플릿을 `TEMPLATE_FILL_TEMPLATE_DIR` 볼륨에 배치.
   템플릿의 누름틀에는 **name 속성(필드명)과 안내문**을 넣어둘 것 —
   이름이 없으면 안내문이 필드명 대용으로 쓰인다.
2. **공유 볼륨**: 워크플로우 pod 와 코드 서빙 pod 가
   `TEMPLATE_FILL_TEMPLATE_DIR`, `TEMPLATE_FILL_SESSION_DIR` 두 경로를 공유해야 한다.
3. **환경변수**: `GENOS_URL`, `LLM_SERVING_ID`, `LLM_MODEL_ID`, `GENOS_TOKEN`(시크릿),
   경로 2종. LLM 없이 구조 검증은 `TEMPLATE_FILL_LLM_MODE=mock`.
4. **캔버스 연결**: 워크플로우 변수 `template_fill_template_id` 로 템플릿 선택 주입.
   Python 노드에 입력이 안 들어오면 코드가 아니라 캔버스 연결부터 확인 (§4.4).
5. **다운로드 버튼**: 코드 서빙 `POST /generate` 에 `{"template_id", "session_id"}` 로 연결.
   버튼 활성화 판단은 `GET /status` 의 `ready_for_download` 사용.

## 로컬 검증

```
cd SFR-006
python -m unittest discover -s template_fill/tests -t .
```

샘플 hwpx 없이 합성 픽스처(`tests/fixtures.py`)로 스캔→채움→재스캔 라운드트립과
멀티턴 세션 누적(mock 모드)을 검증한다.

## 남은 일 / 알려진 한계

- 실제 한/글로 만든 누름틀 템플릿으로 검증 필요 — 한/글 버전에 따라
  `stringParam` 의 name 속성이 다를 수 있어 "첫 stringParam = 안내문"으로 파싱 중.
- 반복 블록(contents 배열 → 문단 복제)은 레거시 `hwpx.py` 에만 있다.
  누름틀 템플릿에서 반복 항목이 필요해지면 `hwpx_fields.py` 로 이식할 것.
- 세션 저장은 last-write-wins — 같은 세션의 동시 다중 턴은 전제하지 않는다.
