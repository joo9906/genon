# AUDIT.md — 현재 코드의 가이드 위반 목록

> Claude Code가 해당 파일을 건드릴 때 **함께 고칠 항목**. 우선순위 순.

## P0 — 배포 전 반드시

| # | 파일 | 문제 | 조치 |
|---|---|---|---|
| 1 | `common/llm.py` | base_url이 `{GENOS_URL}/rep/serving/{id}/v1` — **`/api/gateway` prefix 누락** | 가이드 10.2 경로 `{GENOS_URL}/api/gateway/rep/serving/{id}/v1`로 수정. 운영 GENOS_URL이 gateway를 포함하는지 먼저 확인 |
| 2 | `hwpx_report.py` | `OpenAI()` 외부 SDK + 외부 키 직접 호출 | 10.2 금지 조항. Gateway OpenAI 호환 경로로 교체 |
| 3 | `Weaviate_적재_코드` | 런타임 `subprocess pip install` | 폐쇄망에서 실패. 사전 등록 패키지로 전환 |
| 4 | `Weaviate_적재_코드` | `DECRYPT_KEY`, `WEAVIATE_URL` 등 **시크릿 기본값 하드코딩** | 3.7 위반. 누락 시 즉시 실패로 변경 |

## P1 — 프로덕션 이관 시

| # | 파일 | 문제 | 조치 |
|---|---|---|---|
| 5 | `hwpx_report.py` | `print()` 다수 | `logging.getLogger(__name__)` |
| 6 | `hwpx_report.py` | 전 구간 예외 처리 없음 | `{영역코드}-000200XX` 매핑 |
| 7 | `hwpx_report.py` | LLM 호출 timeout 없음 | timeout + 재시도 상한 |
| 8 | `hwpx_report.py` | `json.loads(result)` 무검증 → 필수 키 없으면 KeyError | 스키마 검증 후 사용 |
| 9 | `hwpx_report.py` | `root.xpath(...)[0]` — 템플릿 문단 없으면 IndexError | 빈 결과 체크 → 명시적 오류 |
| 10 | `hwpx_report.py` | `load_dotenv()` / 로컬 `.env` | 영역별 환경변수 주입 |
| 11 | `Weaviate_적재_코드` | `print()` 다수 | logger |
| 12 | `common/llm.py` | 실패 시 빈 문자열 반환 (예외 없음) — 의도적이지만 상위에서 구분 어려움 | 호출부가 `translation_error`를 반드시 확인하도록 유지 |

## P2 — 개선 여지

| # | 위치 | 내용 |
|---|---|---|
| 13 | `pipeline.py` | `from config import Config` — 다른 모듈은 `translation_pipeline.common.*` 절대경로. import 경로 일관성 필요 |
| 14 | `types.py` | `OfficePipelineDeps`가 정의만 되고 미사용 | 사용하거나 제거 |
| 15 | `prompt_builder.py` | `style_options` 인자를 받지만 시스템 프롬프트에 반영 안 함 | 반영 또는 시그니처 정리 |
| 16 | `translation_modes.py` | `_translate_batch` 재귀 재시도 상한이 하드코딩 `retry < 2` | Config로 노출 |
| 17 | `common/logging_utils.py` | `extra=` 구조화 필드 미지원 (문자열만) | 3.8의 표준 필드 지원 추가 |

## 미해결 이슈

**Flowise → Weaviate 적재 403**
- 증상: 파싱/청킹 성공 → insert 실패, GraphQL 검증 HTTP 403
- 가설 A: Weaviate API key 인증 방식 불일치
- 가설 B: 직접 REST 접근 차단, GenOS gateway 경유 필요
- **다음 시도: B부터.** 가이드상 K8s service DNS 직접 호출은 금지이므로 `WEAVIATE_URL=llmops-weaviate-service` 직접 접근 자체가 규칙 위반이기도 하다
