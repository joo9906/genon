# 이어서 할 일 — SFR-018 내보내기 (2026-08-05 기준)

이 문서는 **다음 작업자가 읽고 바로 이어갈 수 있게** 남긴 것이다.
설계 근거와 계약은 `README.md`, 저장소 전체 맥락은 루트 `CLAUDE.md` 를 본다.

## 지금까지 된 것

| 항목 | 상태 |
|---|---|
| hwpx 되쓰기 코어 (`export_pipeline/hwpx_rewrite.py`) | 완료. 테스트 16건 |
| Redis 세션 저장소 (`session_store.py`) | 완료. 실 Redis 연결 미검증 |
| XLSX 생성 (`xlsx_export.py`) | 완료. openpyxl 로컬 미설치로 실행 미검증 |
| PDF 위임 (`pdf_export.py`) | 완료. **전처리기 변환기로 실제 변환 미검증** |
| 엔드포인트 (`main.py`) | 완료. **HTTP 실행 미검증** (fastapi 로컬 미설치) |
| 글다듬이(02) 연계 | 완료. `export_client` + 번호 정렬. 테스트 22건 |
| 번역(03) 연계 | 완료. `POST /translate/session` |
| 문서 | `README.md`, `onprem/README.md`, 루트 `CLAUDE.md` 갱신 |

## 1. 실제 배포 환경에서 검증해야 하는 것 (가장 먼저)

로컬에 `fastapi`·`openpyxl`·`redis` 가 없어 **엔드포인트를 한 번도 실행하지 못했다.**
문법 검사(`py_compile`)와 순수 로직 테스트만 통과한 상태다. 순서대로 확인한다
(가이드 6장 배포 검증 규약 — health 만으로 끝내지 않는다):

1. `GET /health` → 200
2. `POST /prepare` 에 실제 한/글 제작 hwpx 업로드 → 문단 배열이 문서 순서와 맞는지
   **눈으로 확인**. 합성 픽스처로만 검증했으므로 실제 문서의 run 쪼개짐·표 중첩에서
   어긋날 수 있다.
3. `POST /results` → `GET /status` 의 `ready_for_download` 가 true
4. `POST /export/hwpx` → 내려받은 파일을 **한/글에서 열어본다**. 열리지 않으면
   `charPrIDRef`/`itemCnt` 문제이므로 되쓰기 로직을 다시 본다.
5. `POST /export/pdf` → 변환기 가용성. `pdf_export.document_converter_available()` 로
   먼저 확인하면 원인 분리가 쉽다. 없으면 503 이 나와야 하고, 빈 PDF 가 나오면 버그다.
6. 오류 경로: 잘못된 형식(400), 세션 없음(404), 지문 불일치(400)

## 2. 미해결 설계 질문

- **`EXPORT_SERVING_ID` 로 코드 서빙을 Gateway 경유 호출하는 정확한 경로**를 확인하지
  못했다. 가이드에 `/api/gateway/code_serving/{id}/health` 와 `/requests/validate` 만
  나오고, 등록한 업무 API 를 호출하는 접미사 규약이 명시돼 있지 않다.
  → `export_client._base_url()` 이 `{GENOS_URL}/api/gateway/code_serving/{id}` 를 기본으로
  쓰고, 다르면 `EXPORT_BASE_URL` 로 통째 대체하도록 탈출구를 뒀다. **실제 경로 확인 필요.**
- **클라이언트가 `/prepare` 를 호출하는 UI 연결**이 없다. GenOS 채팅 UI 의 첨부 파일을
  우리 엔드포인트로 넘길 수 있는지가 문서에 없어(플랫폼 팀 확인 사항) 두 경우로 갈린다:
  - 넘길 수 있다 → 업로드 한 번으로 끝난다
  - 못 한다 → 사용자가 대화 시작과 다운로드에 각각 파일을 올린다 (지금 전제)
- **`temp_doc_id` 로 원본을 받는 API** 는 개발가이드 78쪽 전체에 없다. 저장소
  `genos-project/CLAUDE.md:117` 의 주장이고 코드에서 쓰는 곳은 0건이다.
  존재한다면 업로드를 한 번으로 줄일 수 있으므로 플랫폼 팀에 확인할 가치가 있다.

## 3. 남은 구현

- **FAQ 호출부**: FAQ 생성 코드는 이 저장소 밖이다(`SFR-018/README.md:8`).
  `POST /export/xlsx` 와 `POST /export/pdf/markdown` 만 있으면 붙으므로 계약은 준비됐다.
  FAQ 쪽에서 `{items:[{question, answer, sources}]}` 를 보내면 된다.
- **글다듬이 번호 정렬 실패율 관측**: LLM 이 `⟦번호⟧` 를 지키지 못하면 그 문단은 원문이
  유지되고 사용자에게 경고가 뜬다(조용히 틀리지는 않는다). 실사용에서 기각률이 높으면
  문단을 배치로 쪼개 여러 번 호출하는 쪽으로 바꾼다 — 번역 파이프라인의 배치 분할
  (`translation_modes.py`)이 이미 그 패턴이다.
- **번역 `/translate/session` 의 target_lang 주입 경로**: 지금은 요청 본문으로 받는다.
  워크플로우 변수에서 받아야 하면 호출부에서 채운다.
- **두 트리 동기화**: `SFR-018/export/hwpx_rewrite.py` ↔
  `export_pipeline/hwpx_rewrite.py`, `SFR-018/text_polish/paragraph_units.py` ↔
  `onprem/.../paragraph_units.py` 는 같은 코드다(import 경로만 다름). 고칠 때 양쪽을 본다.

## 4. 건드리면 안 되는 것 (이유가 있는 코드)

- `hwpx_rewrite._nearest_paragraph` — `hp:p` 순회로 바꾸면 표 셀 텍스트가 두 번 잡힌다.
- `hwpx_rewrite._section_names` 의 숫자 정렬 — 문자열 정렬은 `section10` 을 `section2`
  앞에 두어 문단 index 가 밀린다.
- 지문 대조 — 없으면 원본이 바뀐 걸 모르고 엉뚱한 문단에 쓴다.
- `mimetype` 을 `ZIP_STORED` 로 쓰는 부분 — 압축하면 한/글이 열지 못한다.
- `paragraph_units.parse_numbered_result` 의 기각 처리 — 채택률을 올리려고 완화하면
  틀린 문단이 조용히 문서에 들어간다.
- `pdf_export` 의 지연 import — 모듈 로드 시점에 import 하면 변환기가 없는 이미지에서
  컨테이너가 아예 뜨지 않는다.

## 5. 검증 명령

```
cd SFR-018 && python -m unittest discover -s export/tests -t .        # 되쓰기 16건
cd SFR-018 && python -m unittest discover -s text_polish/tests -t .   # 문단 정렬 포함 22건
cd SFR-006 && python -m unittest discover -s template_fill/tests -t . # 35건 (openai 미설치 3건 실패는 환경 문제)
```

## 6. 관련 브랜치

| 브랜치 | 내용 |
|---|---|
| `feat/sfr018-export` | 이 단위 + 호출부 연계 (여기) |
| `feat/sfr006-repeat-block` | 반복 블록 이식 + PoC 결함 3개 수정 (FAQ hwpx 가 필요해지면 씀) |
| `docs/mcp-registration-paths` | 평가지표 MCP 등록 경로 문서 |

세 브랜치 모두 **푸시하지 않았다.**
