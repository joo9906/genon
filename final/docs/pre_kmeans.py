"""FAQ k-means 주제 뽑기 — 어느 파일에 어떤 함수가 들어가는지의 설계 스케치.

**실행 코드가 아니다.** 함수 이름·시그니처·역할만 적었고, 본문은 비어 있다.
구현할 때 각 블록을 해당 파일로 옮긴다. 대상은 `final/SFR-018-faq/request/faq/` 와
SDK 판 `final/SFR-018-faq/open_ai/faq/`(갈리는 파일만).

## 흐름

```
document(마크다운)
  → split_units        문단 단위로 자른다                      [topics.py]
  → embed_async        단위마다 임베딩                          [llm.py]
  → kmeans             k 개 주제로 묶는다 (시드 랜덤)           [topics.py]
  → build_topic_inputs 주제마다 LLM 입력을 만든다 (예산 안)     [topics.py]
  → _request_chunk     주제마다 LLM 1회, 몫은 1개              [generator.py, 기존]
  → _adopt             스키마·중복·근거 검증                    [generator.py, 기존]
  → _fill_shortfall    질문을 못 낸 주제만 재시도               [generator.py, 수정]
  → 부족분 안내        "N개만 뽑혔다, 문서를 더 넣어라"         [generator.py + 스텝]
```

## 정한 것

- k = 요청 개수. 용량 계산으로 깎지 않는다. 단위 수가 k 보다 적을 때만 단위 수로 내린다.
- 시드는 기본 랜덤(`None`)이고 테스트만 고정한다. 로그에 시드를 남긴다.
- 주제 입력이 컨텍스트 예산을 넘으면 중심에 가까운 단위부터 예산까지만 싣는다.
- 모자라면 개수를 맞추려 억지로 채우지 않고 부족분을 알린다.
"""


# ═══════════════════════════════════════════════════════════════════════════
# 1. faq/topics.py  (신규) — 순수 함수만. LLM·네트워크를 부르지 않는다
# ═══════════════════════════════════════════════════════════════════════════

def split_units(text: str, min_chars: int, max_chars: int) -> list:
    """문서를 임베딩 단위(문단)로 자른다. **버리는 글자는 없다.**

    1. 빈 줄 기준으로 블록을 나눈다.    2. 마크다운 표(`|` 연속 줄)·한 줄 HTML 표는 블록 하나로 두고 쪼개지 않는다.
    3. 제목 줄(`#`)은 바로 아래 블록에 붙인다 — 제목만 있는 단위는 임베딩이 무의미하다.
    4. `min_chars` 미만 블록은 다음 블록과 합친다.
    5. `max_chars` 초과 블록은 `chunking._hard_split` 으로 자른다.

    `chunking.split_for_context` 와 같은 줄 경계 규칙을 쓴다 — 자르는 규칙이 갈리면
    같은 문서가 경로에 따라 다른 단위로 나뉜다.
    """


def kmeans(vectors: list, k: int, seed=None, max_iter: int = 50) -> list:
    """순수 파이썬 k-means. 각 벡터의 클러스터 번호 목록을 돌려준다.

    - 초기 중심은 k-means++ (`random.Random(seed)`). `seed=None` 이면 실행마다 달라진다.
    - `k` 가 벡터 수보다 크면 벡터 수로 내린다.
    - 코사인 거리를 쓴다 (벡터를 먼저 L2 정규화).
    - 비는 클러스터가 생기면 가장 큰 클러스터에서 가장 먼 점으로 다시 채운다.
    - numpy 에 기대지 않는다 — 사내 mirror 의존을 늘리지 않으려는 선택이다.
    """


def pick_representatives(vectors: list, labels: list, k: int) -> list:
    """클러스터마다 중심에 가까운 순서로 단위 번호를 정렬해 돌려준다. `list[list[int]]`."""


def build_topic_inputs(units: list, vectors: list, labels: list, budget: int) -> list:
    """주제마다 LLM 에 보낼 본문을 만든다.

    - 클러스터에 속한 단위를 중심에 가까운 순서로 `budget` 자까지 싣는다.
    - 실린 단위는 **문서 순서로 다시 정렬해서** 이어 붙인다 (문맥이 앞뒤로 흐르게).
    - 못 실린 단위 수를 같이 돌려준다 → 로그·응답에 남긴다 (침묵 금지).
    """


# ═══════════════════════════════════════════════════════════════════════════
# 2. faq/llm.py  (수정) — 임베딩 호출 추가. URL 은 `_chat_url()` 규칙처럼 한 곳에서
# ═══════════════════════════════════════════════════════════════════════════

async def embed_async(texts: list):
    """단위 목록 → `LlmResult` 같은 값 객체(벡터 목록, error_type, is_transport_error).

    - 한 번에 `EMBED_BATCH` 개씩 나눠 보낸다.
    - mock 모드는 해시 기반 고정 벡터를 돌려준다 (폐쇄망에서 LLM 없이 구조 검증).
    - 실패는 전역 상태가 아니라 값 객체로 돌려준다. 실패하면 호출부가 **기존 조각 방식으로
      되돌아간다** (임베딩이 죽었다고 FAQ 가 안 나오면 안 된다).
    - SDK 판(`open_ai/faq/llm.py`)에도 같은 함수를 넣는다.
    """


# ═══════════════════════════════════════════════════════════════════════════
# 3. faq/config.py  (수정) — 설정 추가. SDK 판 config.py 도 같이
# ═══════════════════════════════════════════════════════════════════════════
#
#   TOPIC_MODE            "kmeans" | "chunk"      기본 kmeans. chunk 면 기존 경로 그대로
#   EMBED_MODEL           임베딩 모델 이름
#   EMBED_BATCH           한 번에 보낼 단위 수
#   TOPIC_UNIT_MIN_CHARS  단위 최소 글자 (합치는 기준)
#   TOPIC_UNIT_MAX_CHARS  단위 최대 글자 (임베딩 입력 한도)
#   TOPIC_SEED            비우면 랜덤. 테스트·재현용으로만 고정


# ═══════════════════════════════════════════════════════════════════════════
# 4. faq/generator.py  (수정)
# ═══════════════════════════════════════════════════════════════════════════

async def _plan_topics(document: str, count: int):
    """`_split` 자리를 대신한다 — 문서를 **주제 입력 목록**으로 바꾼다.

    split_units → embed_async → kmeans → build_topic_inputs 를 한 곳에서 묶는다.
    두 경로(스트리밍·비스트리밍)가 이 함수 하나를 부른다 — 갈리면 같은 문서가 경로에
    따라 다른 주제를 낸다 (`_split` 이 지금 하는 일과 같은 이유).

    임베딩이 실패하거나 단위가 너무 적으면 기존 `_split` 으로 되돌아가고, 되돌아갔다는
    사실을 `FaqResult.topic_mode` 에 남긴다.
    """


# generate_faqs / generate_faqs_stream 에서 바뀌는 곳
#   - `chunks = _split(document, count)`  →  `topics = await _plan_topics(document, count)`
#   - `quota = plan_quota(...)`           →  주제마다 1 (k = count 이므로 합이 count)
#   - `EvidenceChecker("\n".join(chunks))` → 원문 전체로 만든다. 주제 입력은 단위를 일부만
#     싣기도 하므로 **주제 입력을 이어 붙이면 근거 대조 범위가 줄어든다**
#   - `select_spread` 는 쓰지 않는다 (주제 수 = 요청 수라 후보를 덜어낼 일이 없다)
#   - `_adopt` / `_adopt_one` / `seen_questions` 는 그대로


async def _fill_shortfall_topics(topics: list, produced: list, result, checker, seen_questions, total_limit):
    """`_fill_shortfall` 의 주제 판. **질문을 못 낸 주제**부터 다시 부른다.

    - 대상: `produced[i] == 0` 인 주제 (기각돼서 0개가 된 주제 포함).
    - 프롬프트는 `md_retry_shortfall.md` 를 그대로 쓴다 — 이미 채택된 질문 목록을 `existing_block` 으로 준다.
    - 호출 상한 `_MAX_SHORTFALL_CALLS` 는 총량이다 (기존과 같다).
    - 이 재시도로도 못 채우면 억지로 채우지 않고 부족분으로 남긴다.
    """


# FaqResult 에 추가하는 필드 (기존 필드는 그대로)
#   topic_mode        "kmeans" | "chunk"   어느 경로로 돌았나
#   topics_planned    만든 주제 수
#   topics_used       질문을 1개 이상 낸 주제 수
#   topic_seed        이번 실행의 시드 (재현용)
#   unit_dropped      예산에 못 실린 단위 수
#   shortfall         요청 − 실제 개수 (0 이면 부족 없음)


# ═══════════════════════════════════════════════════════════════════════════
# 5. final/workflow/sfr018_faq_02_*.py  (수정) — 안내문
# ═══════════════════════════════════════════════════════════════════════════
#
#   - `shortfall > 0` 이면 "문서에서 N개만 뽑혔습니다. 더 필요하면 문서를 추가해 주세요" 를 낸다.
#   - 기각 사유별 건수(`rejected_schema/duplicate/ungrounded`)를 같이 보여 준다 —
#     "문서가 짧다" 와 "LLM 형식 오류" 를 구분할 수 있어야 한다.
#   - 기존 `chunks_used < chunks_planned` 안내문 자리가 `topics_used < topics_planned` 로 바뀐다.


# ═══════════════════════════════════════════════════════════════════════════
# 6. 그 밖에
# ═══════════════════════════════════════════════════════════════════════════
#
#   - Test/SFR-018/tests/test_topics.py  (신규)  split_units · kmeans(고정 시드) · build_topic_inputs
#   - Test/run_all.py 의 EXPECTED 를 늘어난 건수로 고친다
#   - final/docs/DESIGN_NOTES.md  FAQ 절에 근거를 남긴다:
#       · 주제 입력이 예산을 넘으면 일부 단위가 LLM 에 안 간다 (조각 방식의 "전부 본다" 규약을 이 경로는 포기)
#       · 시드가 랜덤이라 같은 문서도 실행마다 결과가 다르다
#   - final/docs/FEATURES.md  FAQ 항목에 새 설정을 올린다
