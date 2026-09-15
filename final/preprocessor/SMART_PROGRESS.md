# `smart_preprocessor.py` (지능형 + hwpx) — 진행 기록

> 세션이 끊기면 이 파일부터 읽는다. **결과물 설명은 파일 자신의 머리말과
> `README.md` 가 정본**이고, 여기는 "어떻게 만들었나 / 어디서 헛걸음했나" 만 남긴다.

## 요구 (2026-09-08)
**지능형 전처리기가 실환경에서 돈다는 것이 확인됐다.** 그래서 **지능형(pdf·docx…) +
우리 hwpx 파서**를 짝지은 등록 단위를 하나 만든다. **스키마를 맞춰 UI 에서 레코드가
누락되지 않게** 하는 것이 요점.

> 2026-09-03 에 "지능형은 앞으로 쓰지 않는다" 로 확정했던 것이 **뒤집혔다.** 그때 근거는
> 사이트 설치본 판본과 어긋나 pdf 적재가 `ModuleNotFoundError` 로 막혔다는 것이었다.

## 결정 사항 (되묻지 말 것)
- **`final_preprocessor.py` 를 고치지 않고 새 파일을 만든다.** 둘은 **같은 자리를 두고
  겨루는 판본**이고 등록은 하나만 한다. 한 파일에 kwargs 로 벤더를 고르게 하지 않은
  이유는 `only_me.py` 때와 같다 — **kwargs 를 빠뜨린 등록이 조용히 다른 절반을 쓴다.**
- **hwpx 절반(PART 2)은 `final_preprocessor.py` 것을 그대로 쓴다.** 두 벌이 갈리면 같은
  hwpx 가 어느 단위로 적재했느냐에 따라 다른 청크로 들어간다 — 점검이 그 둘을 대조한다.
- **조/항/호 위계를 지능형 경로에 걸지 않았다** (첫 판). `final_preprocessor` 의
  `_fp_enable_outline` 은 첨부용 산출물 모양(langchain `Document` 목록)을 전제로 만든
  배선이라 지능형(`DoclingDocument` + `GenosSmartChunker`)에 그대로 얹을 수 없다.
  잘못 걸면 **매 요청 실패한 뒤 벤더 청커로 돌아가 위계가 영영 안 붙는데 결과는 정상으로
  보인다.** hwpx 의 조문 위계는 그대로다.
- **빌드 스크립트를 저장소에 남기지 않는다.** 2026-09-03 에 걷어낸 이유(보는 파일과
  치는 파일이 달라진다)가 그대로 유효하다. 조립은 **일회성**으로 하고 산출물만 정본으로
  두되, **`check_smart_preprocessor.py` 가 참조 원본에서 다시 계산해 대조**한다 —
  빌드의 그물만 남기고 빌드는 남기지 않는 것이다.

## 어떻게 만들었나

`genos_files/intelligence_processor.py`(3,544줄) + `final_preprocessor.py` 의 PART 2 +
새로 쓴 라우터 = **6,553줄**.

1. **이름 충돌은 여덟인데 실제로는 둘이다.** 나머지 여섯(`os`·`re`·`time`·`logging`·
   `datetime`·`Any`)은 같은 표준 모듈이라 덮여도 같다.

   | 원래 이름 | 바꾼 이름 | 안 바꾸면 |
   |---|---|---|
   | `DocumentProcessor` | `IntelligentDocumentProcessor` | 지능형 것이 **라우터를 덮어** hwpx 가 영영 안 탄다 |
   | `_log` | `_intel_log` | 어느 절반이 낸 로그인지 사라진다 |

2. **개명은 토큰 단위로.** 정규식으로 갈면 지능형의 `[DocumentProcessor]` 로 시작하는
   로그 문자열까지 바뀐다(MCP 넷을 합칠 때 `resolve_tone` 에서 밟은 함정).
3. **들여쓰기는 여러 줄 토큰을 피해서.** 지능형 절반이 통째로 `try:` 안으로 들어가는데,
   여러 줄 문자열 안쪽 줄에 공백을 붙이면 **그 문자열의 내용이 바뀐다.**
4. **검증은 AST 로.** 들여쓴 결과를 다시 파싱해 원본과 `ast.dump` 를 대조했다 —
   토큰 치환·들여쓰기가 무언가를 건드렸으면 여기서 갈린다.

## 스키마 — UI 누락 방지가 요구의 핵심이었다

두 가지를 한다:

1. **페이지 자리에 구역(section)** — hwpx 는 흐름 문서라 렌더링 전에 페이지가 없는데,
   적재 결과 **화면이 `i_page` 로 청크를 묶어 그린다.** 비우면 hwpx 로 넣은 문서만
   화면에 안 뜬다(빈 목록이라 오류가 없다). 1-based `i_page`, 0-based
   `i_chunk_on_page`, `chunk_bboxes="[]"`, `media_files=""` — 전부 **벤더가 못 찾았을 때
   내는 값과 같은 것**이다. 출처는 `page_basis` 가 말한다.
2. **벤더 예약 필드** — `_sp_align_records`. **목록을 손으로 적지 않고 지능형
   `GenOSVectorMeta` 에서 뽑는다.** 벤더가 필드를 늘리면 따라간다. 벤더 절반이 안 떴을
   때를 대비해 baseline(`title`·`created_date`·`appendix`·`guardrail_categories`)을
   함께 둔다 — 그때 정렬을 건너뛰면 **그 환경에서 넣은 레코드만 모양이 달라진다.**

실물(`data/파워.hwpx`)로 확인한 레코드 키 24개에 지능형 예약 필드가 전부 들어 있다.

## 밟은 것

1. **점검이 들여쓰기를 되돌릴 때 보호 구간까지 깎았다.** `line[4:]` 로 단순 dedent
   했더니 **원래 4칸으로 시작하던 docstring 줄**이 깎여 문자열 33개가 달라졌고, 점검이
   "합치기가 원본을 건드렸다" 고 **잘못 고발했다.** 합칠 때와 **같은 보호 규칙**을
   점검에도 넣어 해결.
2. **되돌리기 하나가 엉뚱한 데를 맞혔다.** `[DocumentProcessor]` 문자열을 바꿔 FAIL 을
   보려 했는데 `replace(..., 1)` 가 **PART 0 머리말**의 같은 낱말을 먼저 맞혔다 —
   그래서 "안 잡힌다" 고 잘못 읽었다. 지능형 절반 **안의** 문자열을 AST 로 골라 다시
   확인하니 2건 FAIL 했다.
3. **`sys.modules` 에 먼저 넣어야 import 된다.** 파일 경로로 로드할 때 등록을 빠뜨리면
   `dataclasses` 가 `sys.modules[cls.__module__]` 를 읽다 죽는다 — **우리 코드와 무관한
   자리**에서 실패해 원인을 엉뚱한 데서 찾게 된다.

## 그물 — `onprem/test/check_smart_preprocessor.py` (52건)

되돌려 FAIL 을 확인한 갈래는 **다섯**이다:

| 되돌린 것 | FAIL |
|---|---|
| 개명 한 자리(`_intel_log` → `_log`) | 2건 |
| 지능형 절반 안의 문자열 하나 | 2건 |
| 스키마 정렬 건너뛰기 | 4건 |
| `i_page` 를 0-based 로 | 3건 |
| hwpx 절반만 몰래 고치기 | 1건 |

**SKIP 1건은 통과가 아니다** — 로컬에 docling 스택이 없어 지능형 절반이 `try` 에 걸린다.
그 상태에서도 라우팅·kwargs 전달·스키마 정렬은 **대역을 등록 단위 밖에서 꽂아** 본다.

## 남은 것 / 확인 필요
- **지능형 경로 실행은 미검증** (로컬에 docling 없음). 폐쇄망에서 pdf 한 벌을 넣어
  `event=smart_preprocess_routed status=intel` 과 레코드 수를 볼 것.
- **설정 yaml 을 찾는지 미확인.** 지능형 `_load_config` 는 파일이 없으면 **예외를 던진다**
  (첨부용은 `{}` 로 넘어간다). 못 찾으면 `_acquire` 가 `SmartPreprocessorError` 로 감싸
  어느 파일이 없는지 드러낸다 — 후보를 넷 뒀다(`_sp_resolve_config_path`).
- **`.hwp`·`.hml`·오디오는 지능형에 네이티브 경로가 없다.** 라우터가 만날 때마다
  `event=smart_preprocess_vendor_gap` 으로 알린다. 그 형식이 필요하면
  `final_preprocessor.py` 로 등록한다.
- **조/항/호 위계를 지능형 경로에도 걸려면** `_fp_outline_chunks` 계열을
  `GenosSmartChunker` 에 맞춰 다시 배선해야 한다 — 위 "결정 사항" 참고.
