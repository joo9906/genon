# CLAUDE.md — GenOS 문서처리 파이프라인 프로젝트

> Claude Code 작업 지시서. 이 저장소에서 코드를 쓰거나 고칠 때 **먼저 이 파일과 `docs/GENOS_RULES.md`를 읽는다.**
> 규칙 위반은 배포 리젝 사유다. "동작하는 코드"보다 "가이드를 지키는 코드"가 우선이다.

---

## 0. 30초 요약

- **환경**: Genon AI 사내 **GenOS 온프레미스 / 폐쇄망(closed network)**
- **목표**: HWP/HWPX(한글) 문서를 LLM 파이프라인에 태워 **필드 추출 / 템플릿 채우기 / 번역 / FAQ 생성**
- **아님**: RAG·벡터DB 적재가 주 목적이 아니다. (Weaviate 적재 코드는 별도 곁가지 실험)
- **제약**: pip 설치만 가능. `apt`, LibreOffice 등 시스템 레벨 도구 **설치 불가**
- **HWPX→PDF 변환**: 다른 담당자가 별도 서비스로 처리. 이 저장소 범위 밖
- **모든 코드**: `260721_GenOS_엔지니어_개발가이드_v1.02` 준수

---

## 1. 실행 영역 (Area) — 지금 다루는 것

GenOS는 사용자 코드를 8개 영역으로 나눈다. 이 프로젝트가 쓰는 건 4개다.
**어떤 영역인지 먼저 확정하고 코드를 써라. 영역마다 함수 시그니처·오류 전달 방식·오류 영역코드가 전부 다르다.**

| 영역 | 진입점 | 반환 | 오류 영역코드 |
|---|---|---|---|
| 워크플로우 Python 단계 | `run(data)` (모듈 최상단) | dict 또는 스트리밍 이벤트 | `02` |
| 코드 서빙 | 웹앱 (`0.0.0.0:$PORT`, `GET /health`) | HTTP response | `03` |
| Flowise Custom JS Function | 코드 블록 + 명시적 `return` | 객체/문자열/숫자 | `04` |
| 전처리기 | `DocumentProcessor.__call__(request, file_path, **kwargs)` | `list[dict]` (`text` 키 필수) | `05` |

> 전처리기·평가지표는 **오류 객체를 반환하지 않는다.** 로그에 코드를 남기고 **예외를 던진다.**
> 워크플로우/코드서빙/Flowise는 **예외 대신 오류 객체**를 반환한다.

---

## 2. 저장소 구성

```
translation_pipeline/          # 코드 서빙 (Office/HWPX 번역) — area 03
  common/
    error_codes.py             # ⭐ 오류 코드 단일 소스. 문자열 직접 쓰지 말고 여기 상수 import
    config.py                  # 환경변수. 시크릿 기본값 금지
    llm.py                     # Gateway 경유 LLM 호출 (재시도 상한 있음)
    logging_utils.py           # print 금지. logger만
    prompt_builder.py          # 프롬프트 문자열 분리
    validation.py              # LLM 배치 응답 검증 (개수/id 불일치 방어)
  office/
    types.py                   # TranslationUnit / OfficeTranslationArtifacts / deps
    units.py                   # 노드 ↔ 번역단위 변환
    translation_modes.py       # llm / mock / noop 분기 + 배치 분할 + 폴백
    pipeline.py                # 오케스트레이션. main은 이것만 안다
  main.py                      # FastAPI. /health, /translate

hwpx_report.py                 # ⚠️ PoC 스크립트. 가이드 미준수. 리팩터링 대상 (§7)
Weaviate_적재_코드              # ⚠️ 곁가지 실험. 미해결 이슈 있음 (§6.3)
첨부용_전처리기 / 지능형_전처리기   # GenOS 제공 참조 구현 (읽기 전용 레퍼런스)
```

### 계층 규칙
`main.py` → `pipeline.py` → `translation_modes.py` → `llm.py`
위층은 아래층의 **한 개 진입 함수만** 안다. 역방향 import 금지. 계층 건너뛰기 금지.

---

## 3. 도메인 지식 (HWP/HWPX) — 매번 다시 알아내지 말 것

### 3.1 HWPX 구조
- hwpx = **ZIP + XML**. 본문은 `Contents/section0.xml`(멀티 섹션이면 `sectionN.xml`)
- 네임스페이스: `hp` = `http://www.hancom.co.kr/hwpml/2011/paragraph`
  → **네트워크 주소가 아니라 태그 식별자다.** 폐쇄망에서 접속 시도하지 말 것
- 문단 텍스트 노드: `{http://www.hancom.co.kr/hwpml/2011/paragraph}t`
- 파싱은 `lxml` 사용

### 3.2 ⚠️ 문단 id는 신뢰 불가
모든 문단의 `id` 속성이 `2147483648`로 **전부 중복**된다.
→ **id 기반 주소 지정 금지.** 토큰 기반 또는 인덱스 기반만 사용.

### 3.3 채우기 전략 — 토큰 기반이 기본
| 전략 | 방식 | 언제 |
|---|---|---|
| **토큰 기반 (기본)** | `{{field}}` 문자열 치환 | 새로 만드는 템플릿 전부 |
| 로케이터 기반 | `para_index`, `(table_index, row, col)` | 편집 불가한 기성 문서만 |

**이유**: LLM 출력은 길이가 매번 달라진다. 앞쪽에 긴 내용이 들어가면 로케이터 인덱스가 밀려서 깨진다.
토큰 위치는 길이와 무관하게 안정적이다.

### 3.4 반복 블록 생성 패턴
템플릿 문단 하나를 `deepcopy`해서 텍스트만 갈아끼우고 `parent.insert()` — 서식(`paraPrIDRef`)이 보존된다.
작업 끝나면 원본 템플릿 문단을 `remove()` 한다. (`hwpx_report.py`의 `□`/`◦` 처리 참고)

### 3.5 표(table) 직렬화
- `export_to_markdown()` → 병합셀 구조가 **뭉개진다**
- `export_to_html()` → `colspan`/`rowspan` **보존**
→ 표 채우기 워크플로우는 **HTML 직렬화를 쓴다.**

### 3.6 전처리기 선택
**첨부용(attachment) > 지능형(intelligent)** — HWP/HWPX 한정.
- 첨부용: 네이티브 `HwpProcessor` 경로 + 3단 폴백 (GenosHwp SDK → 레거시 backend → …)
- 지능형: **무조건 PDF로 변환 후 처리** → 구조 정보 손실

### 3.7 폰트
- 운영: 함초롬바탕 / 함초롬돋움 (HCR 시리즈)
- 테스트: Noto CJK — 레이아웃이 미세하게 틀어짐. 검증용으로만.

---

## 4. GenOS 런타임에서 데이터가 오는 위치

### 4.1 워크플로우 Python 단계 — 업로드 문서
```python
config    = data.get('overrideConfig') or {}
variables = config.get('vars') or {}
docs_val  = variables.get('genosUploaded') or ""   # 문자열
```
`genosUploaded`는 XML 유사 블록 문자열이다:
```
<doc file_name="..." temp_doc_id="...">본문 내용</doc>
```
정규식보다 **관대한 파서**로 처리하고, 형식이 어긋나면 조용히 넘기지 말고 오류를 낸다.

### 4.2 시스템 주입 컨텍스트
```python
state = data.get("genos_state", {})
state["trace_id"]           # 분산추적 UUID — 외부 호출에도 전달
state["session_id"]         # 대화 세션. 이전 대화를 자동으로 넣어주진 않음
state["genos_user_id"]
state["genos_resource_id"]  # workflow id
```

### 4.3 채팅 화면에 답변 노출 (스트리밍)
```python
try:
    from main_socketio import sio_server
except ImportError:
    sio_server = None
sid = data.get('socketIOClientId')
# token 이벤트 반복 → 마지막에 반드시 result 이벤트
yield {"event": "result", "data": {"text": answer}}
```
**`result`를 안 보내면 답변이 완결되지 않는다.**

### 4.4 ⚠️ 알려진 함정 — Python 노드에 문서가 안 들어올 때
`data`에 `genos_state`, `overrideConfig`, `question`, `text`만 있고 문서가 없다면
**코드 버그가 아니라 GenOS 워크플로우 캔버스의 입력 노드 연결 누락이다.** 코드를 파지 말고 캔버스를 확인하라고 안내할 것.

---

## 5. 코딩 컨벤션 (이 저장소 고유)

- 오류 문자열 하드코딩 금지 → `common/error_codes.py`의 `ErrorCode` 상수 import
- `print()` 금지 → `logging.getLogger(__name__)`
- 외부 호출은 **전부** `timeout` 명시. 재시도는 **상한 있는 for 루프**만
- LLM 응답을 **믿지 않는다** → `validation.py`처럼 기대값과 대조 후 정상 항목만 채택
- 실패를 **침묵 처리하지 않는다** → 원문 폴백을 하더라도 `translation_error`처럼 실패 사실을 상위로 노출
- 테스트 모드(`mock`/`noop`)를 항상 남긴다 → 폐쇄망에서 LLM 없이 파이프라인 구조 검증
- Docstring에 **어떤 가이드 조항 때문에 이렇게 썼는지** 남긴다 (기존 파일들 스타일 유지)
- 상수/커넥션 정보는 프로젝트 constants에서 하드코딩, `$vars`에서는 `genosUploaded`만 읽는다

---

## 6. 현재 상태

### 6.1 진행 중
- **HWPX 템플릿 채우기 시스템**: manifest 기반 필드 스키마. 관리자가 UI에서 필드 타입/검증규칙/기본값 설정.
  검증 규칙은 **선언적 프리셋(phone, email, digits)** 으로 제공한다 — 비개발자 관리자가 정규식을 쓰게 하지 않는다.
- **번역 파이프라인 (코드 서빙)**: 위 구조로 동작 중

### 6.2 진단 완료된 이슈
- 워크플로우 Python 노드 입력 누락 → 캔버스 연결 문제 (§4.4)

### 6.3 미해결
- **Flowise → Weaviate 적재**: 파싱/청킹은 성공. **insert 실패 + GraphQL 검증 HTTP 403**.
  가설 두 가지 — (a) Weaviate API key 인증 방식 불일치, (b) 직접 REST 접근 차단, GenOS gateway 경유 필요.
  → 건드리게 되면 **(b) gateway 경유부터 시도**. K8s service DNS 직접 호출은 가이드상 금지다.

---

## 7. 리팩터링 대기 (건드리면 같이 고칠 것)

`hwpx_report.py` — 로컬 PoC라 가이드를 거의 안 지킨다. 프로덕션에 옮길 때 반드시:
1. `print()` → `logger`
2. `OpenAI()` 직접 SDK + 외부 키 → **GenOS Gateway OpenAI 호환 경로** (가이드 10.2, 우회 호출 금지)
3. `load_dotenv()` / 로컬 `.env` → 영역별 환경변수 주입
4. timeout 없음 → 전 호출 timeout 명시
5. 예외 처리 없음 → `{영역코드}-000200XX` 오류 처리
6. `json.loads(result)` 무검증 → 스키마 검증 후 사용
7. `xpath(...)[0]` — 템플릿 문단 못 찾으면 IndexError → 명시적 오류로 변환

`Weaviate_적재_코드` — 런타임 `pip install` (subprocess), `print()`, 시크릿 기본값 하드코딩. 동일하게 정리 필요.

---

## 8. 작업할 때 지켜야 할 절차

1. **영역 확정** — 워크플로우 단계인가, 코드 서빙인가, 전처리기인가? (§1)
2. **`docs/GENOS_RULES.md` 체크리스트 통과 확인**
3. 새 오류 유형이면 `error_codes.py`에만 추가 — 공통코드는 `00020001/2/3` 셋만 조합
4. 외부 호출 추가 시 timeout + 재시도 상한 + 오류코드 매핑 3종 세트 동시 작성
5. 완료 후 `docs/GENOS_RULES.md` §체크리스트로 self-review

**모르면 추측하지 말고 물어본다.** 특히 GenOS 화면 설정(캔버스 연결, 환경변수 등록 위치)은 코드로 해결 못 하는 게 많다.
