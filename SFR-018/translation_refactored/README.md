# 번역 코드 서빙 (리팩토링판)

Office/HWPX 문서 노드 번역 FastAPI 서비스 (GenOS 코드 서빙, area 03).

## 구조 이력

원래 이 폴더에는 리팩토링된 4개 파일(`main.py`, `llm.py`, `pipeline.py`,
`translation_modes.py`)만 평면으로 있었고, import 가 가리키는
`translation_pipeline.*` 패키지와 `config.py`, `types.py`, `units.py` 등이
없어 **단독 실행이 불가능했다.** (원본은 `genos-project/source/` 에 평면 보관)

2026-08-03 정리: 리팩토링 파일을 패키지 위치로 이동하고, 변경이 없던
의존 모듈을 `genos-project/source/` 에서 복사해 자립 실행 가능하게 조립했다.

```
main.py                              # FastAPI 진입점 (/health, /translate, /translate/markdown)
config.py                            # 환경변수 (시크릿 기본값 없음)
translation_pipeline/
  common/
    error_codes.py                   # 오류 코드 단일 소스
    llm.py                           # ★리팩토링: LlmResult로 전역 레이스 제거
    logging_utils.py
    prompt_builder.py
    validation.py                    # LLM 배치 응답 검증
  office/
    pipeline.py                      # ★리팩토링: trans_map 키 충돌 계약 명시
    translation_modes.py             # ★리팩토링: 실패 유닛 명시 추적 + 병렬 fallback
    markdown_units.py                # ★마크다운 구조 보존 분해/재조립
    types.py
    units.py
tests/                               # noop 무손실 라운드트립 + 구조 불변 검증
```

## 마크다운/HTML 입력 경로 (전처리기 산출물)

docx/pdf/hwpx 를 전처리기가 변환해 넘기는 경우
`POST /translate/markdown` `{"markdown", "target_lang", "translator_mode"?}` 사용.
전처리기 유형에 따라 표 형식이 다르며 **둘 다 커버한다**:

| 전처리기 | 표 형식 | 처리 방식 |
|---|---|---|
| 첨부용(attach_processor) | 마크다운 표 `\| a \| b \|` + `<!-- PB -->` 페이지 마커 | 파이프/구분행/마커 리터럴, 셀 텍스트만 유닛 |
| 지능형(intelligence_processor) | 한 줄 HTML 표 `<table><tbody>…` (셀 escape, colspan) | 태그 전부 리터럴, 텍스트 노드만 유닛 (unescape→번역→재escape) |

표 파이프·HTML 태그·제목(#)·목록·인용·코드펜스는 `markdown_units.py` 가
스켈레톤으로 분리해 코드가 보존하고, 셀/문장 **텍스트만** 번역 유닛으로 보낸다.
따라서 응답 `markdown` 의 구조는 LLM 출력 품질과 무관하게 입력과 항상 동일하다.
숫자·기호만 있는 셀과 코드블록은 LLM 을 거치지 않고 원문 유지.

계약 검증: `python -m unittest discover -s tests -t .` (noop 모드 = 입력과 바이트 동일)
알려진 정규화: HTML 셀의 `&quot;`/`&#x27;` 엔티티는 왕복 시 원문 문자(`"`/`'`)로
정규화된다 (의미 동일). `&amp;`/`&lt;`/`&gt;` 는 바이트 단위 보존.

계층 규칙(위층은 아래층의 진입 함수 하나만): `main → pipeline → translation_modes → llm`

## 실행

```
cd translation_refactored
set GENOS_URL=... & set LLM_SERVING_ID=... & set LLM_MODEL_ID=... & set GENOS_TOKEN=...
uvicorn main:app --host 0.0.0.0 --port %PORT%
```

LLM 없이 구조 검증: 요청 본문에 `"translator_mode": "mock"` (또는 `noop`).
