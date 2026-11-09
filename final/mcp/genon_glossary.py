# =====================================================================================
# genon_glossary — 사내 용어사전 조회 MCP 도구 (area 01)
#
# **이 파일 하나가 등록 단위다.** GenOS MCP 는 소스 파일 한 개를 받아 실행하며,
# `mcp` 객체를 런타임이 전역으로 주입한다. 그래서 패키지로 쪼갤 수 없다.
#
# **모든 최상위 심볼에 `GL` 접두어를 붙였다.** 한 서버에 다른 도구 파일이 함께 로드될 수
# 있어서다.
#
# ## 지금 무엇이 있고 무엇이 없나
#
# **1단계(완전 일치 + 활용형 정규화)만 있다.** 2단계(Weaviate + 임베딩 게이트웨이)는
# 폐쇄망 벡터DB 가용성이 확인되지 않아 보류다.
#
# **2단계 폴백이 없다는 것이 중요하다.** 사전이 없거나 캐시 상한을 넘으면 그 언어는
# **용어사전 없이** 번역된다. 그래서 `glossary_status` 가 적재 상태를 그대로 노출하고,
# `glossary_lookup` 도 `enabled=false` + `reason` 을 낸다 — 호출부가 "용어사전이 적용된
# 결과" 와 "적용되지 않은 결과" 를 구분할 수 있어야 한다.
#
# ## 준수율(compliance)은 여기 없다 — 의도한 것이다
#
# 준수율 계산은 번역 파이프라인의 `TranslationUnit` 객체를 받는다. JSON 으로 넘길 수 없고,
# MCP 용으로 다시 구현하면 **같은 준수율 규칙이 두 벌**이 된다. 번역 코드서빙 응답
# (`glossary.compliance`)에 그대로 둔다.
#
# ## 적재는 **GenOS 독립 용어사전(`데이터 > 용어사전`) API** 에서 한다
#
# `GET {TRANSLATE_GLOSSARY_API_URL}/data/glossaries/{TRANSLATE_GLOSSARY_ID}/attributes`
# `GET {TRANSLATE_GLOSSARY_API_URL}/data/glossaries/{TRANSLATE_GLOSSARY_ID}/terms`
# **이름이 `ko` · `en` 인 속성**(없으면 대표어를 한국어로)을 읽고 양방향으로 색인한다.
# 첫 도구 호출에서 적재한다(기동 훅이 없다 — 아래 `_GLensure_loaded`).
#
# **매칭 규칙은 번역 코드서빙(`glossary_store.py` · `glossary_exact.py`)과 같다** — 한 원문의
# 후보 전부(`text[]` 값 전부 · `;` 동의어), 같은 (한국어, 영어) 쌍만 거름, 표제어도 원문과 같은
# `_GLTOKEN_RE` 토큰화(숫자도 독립 토큰), 문서 쪽 조사·동사 활용(-ed/-ing) 폴백, 대소문자만 다른
# 원문은 한 묶음. 한쪽만 고치면 같은 질문에 다른 답이 나온다.
#
# **설치가 필요한 패키지를 쓰지 않는다.** stdlib 만으로 돈다 (조회는 `urllib`).
# `pydantic` 하나를 **선택적으로**(try/except) 가져다 쓰는데, MCP 런타임(FastMCP)이 도구
# 스키마를 만들 때 이미 쓰는 패키지라 따로 설치할 것이 아니고, 없으면 선택지 없이 그냥
# 돈다 (아래 "선택지를 도구 스키마에 싣는다" 절).
# =====================================================================================

import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from typing import Annotated

# ── logging_utils.py ─────────────────────────────
# 3.8절 기록 허용 필드. 이 목록을 늘리려면 가이드 근거가 있어야 한다.
GLALLOWED_FIELDS = frozenset(
    {
        "event",
        "trace_id",
        "request_id",
        "resource_id",
        "status",
        "duration_ms",
        "item_count",
        "upstream_status",
        "error_code",
        "error_type",
    }
)

# 로거 이름은 **파일 이름**이다. 번역 코드서빙에서 옮겨 오며 `translation_pipeline`
# 그대로였는데, 그러면 이 MCP 가 남긴 줄이 그 서빙의 로그처럼 보인다.
_GLlog = logging.getLogger("genon_glossary")


# GenOS 런타임 로거(`common/logger.py`)와 같은 형식이다. 그 형식은 `extra` 를 찍지 않으므로
# 허용 필드는 포매터가 줄 끝에 붙인다. 스트림은 stderr 그대로다(아래 `_GLsetup_logging`).
_GLLOG_FORMAT = "%(levelname)s: %(asctime)s|[%(filename)s:%(lineno)s - %(funcName)20s() ] %(message)s"
_GLLOG_DATEFMT = "%Y-%m-%d %H:%M:%S %Z"
_GLLOG_FIELDS = (
    "event", "trace_id", "request_id", "resource_id", "status",
    "duration_ms", "item_count", "upstream_status", "error_code", "error_type",
)


class _GLFieldFormatter(logging.Formatter):
    def formatMessage(self, record: logging.LogRecord) -> str:
        line = super().formatMessage(record)
        pairs = [
            f"{key}={' '.join(str(getattr(record, key)).split())}"
            for key in _GLLOG_FIELDS
            if getattr(record, key, None) is not None
        ]
        return f"{line} | {' '.join(pairs)}" if pairs else line


def _GLsetup_logging() -> None:
    """이 파일 전용 **stderr** 핸들러를 붙인다.

    두 가지를 동시에 지키려는 것이다:

    - **`print()` 를 쓰지 않는다** (GENOS_RULES §C). MCP 는 stdout 이 전송 채널이 될 수
      있고(stdio 방식), 그러면 로그 한 줄이 프로토콜을 깨뜨린다 — `eval/` 이 stderr 전용
      로깅을 쓰는 이유와 같다.
    - **그렇다고 조용해지지도 않는다.** 로깅 설정이 없는 프로세스에서 `logger.info` 는
      **아무 데도 안 나온다**(기본 최후 핸들러가 WARNING 부터다). 그냥 logger 로 바꾸기만
      하면 부팅·적재 메시지가 소리 없이 사라진다 — 그건 print 보다 나쁘다.

    핸들러가 이미 있으면 아무것도 하지 않는다(런타임이 설정했다면 그쪽을 존중한다).
    """
    if _GLlog.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_GLFieldFormatter(_GLLOG_FORMAT, _GLLOG_DATEFMT))
    _GLlog.addHandler(handler)
    _GLlog.setLevel(logging.INFO)
    # 루트로 올리지 않는다 — 루트에 stdout 핸들러가 붙어 있으면 그리로 새어 나간다.
    _GLlog.propagate = False


_GLsetup_logging()


def _GLprepare(message: str, event: str, fields: dict) -> tuple[str, dict]:
    extra: dict = {"event": event}
    dropped = []
    for key, value in fields.items():
        if key == "event" or key not in GLALLOWED_FIELDS:
            dropped.append(key)
            continue
        if value is not None:
            extra[key] = value
    if dropped:
        # 값은 남기지 않고 필드명만 — 호출부 실수를 드러내되 내용은 새지 않게
        message = f"{message} [dropped_fields={','.join(sorted(dropped))}]"
    return message, extra


def gllog_info(message: str, *, event: str, **fields) -> None:
    text, extra = _GLprepare(message, event, fields)
    _GLlog.info(text, extra=extra, stacklevel=2)


def gllog_warning(message: str, *, event: str, **fields) -> None:
    text, extra = _GLprepare(message, event, fields)
    _GLlog.warning(text, extra=extra, stacklevel=2)


# ── glossary_exact.py ─────────────────────────────
# 캐시 상한. 초과하면 그 언어의 용어사전 적용을 비활성화한다.
_GLDEFAULT_MAX_CACHED_TERMS = 300_000

# 용어 하나가 가질 수 있는 최대 단어 수. 이보다 긴 항목은 "용어"가 아니라 문장/조항으로
# 보고 제외한다 — 정확 매칭될 확률이 낮고 오탐만 늘린다.
_GLMAX_TERM_WORDS = 6


@dataclass(frozen=True, slots=True)
class GLGlossaryTerm:
    term_source: str
    term_target: str
    domain: str = ""


# 영어 단어를 단수/기본형에 가깝게 되돌리는 규칙. 완전한 표제어 추출은 아니지만
# 용어사전 매칭 목적에는 실용적이다. 순서가 중요하다(구체적인 패턴 먼저).
_GLEN_SUFFIX_RULES: list = [
    ("ies", "y"),    # categories -> category
    ("ves", "f"),    # knives -> knife
    ("xes", "x"),    # boxes -> box
    ("ches", "ch"),  # matches -> match
    ("shes", "sh"),  # dishes -> dish
    ("s", ""),       # invoices -> invoice (가장 일반적 — 마지막에 검사)
]

# 지원 6개 언어의 글자를 토큰으로 잡는다. 원본 실험은 영어·한국어만 다뤘지만
# 이 배포 단위는 중국어·태국어·베트남어·러시아어 사전도 받는다.
#   - 한글 / 라틴(베트남어 성조 포함) / 키릴 / 한자 / 태국 문자
#   - 태국어·중국어는 띄어쓰기가 없어 토큰이 길게 잡힌다 → 그 언어 사전은
#     사실상 완전 일치만 걸린다 (한계로 문서화).
_GLTOKEN_RE = re.compile(
    r"[A-Za-zÀ-ɏ]+"      # 라틴 + 확장(베트남어)
    r"|[가-힣]+"            # 한글
    r"|[Ѐ-ԯ]+"            # 키릴(러시아어)
    r"|[一-鿿]+"            # 한자(중국어)
    r"|[฀-๿]+"            # 태국 문자
    r"|[0-9]+"              # 숫자 — 독립 토큰이라 `1차` 는 (`1`,`차`)이고 `2차` 와 안 맞는다
    r"|[,，、;；:：.。!！?？/／|｜·ㆍ・•‧()（）\[\]{}「」『』《》〈〉…]",  # 문장부호 — 독립 토큰(경계)
    # 문장부호를 한 글자씩 토큰으로 남겨 용어가 그 너머로 이어지지 않게 한다 — 버리면
    # `mortgage, loan` 이 `Mortgage loan` 에, `신용·대출` 이 `신용 대출` 에, 표 칸 `| 주택 | 대출 |` 이
    # `주택 대출` 에 걸린다. 표제어 쪽 부호는 반대로 **있어도 없어도 되는 자리**다(`_GLseq_len`) —
    # `401(k)` 는 원문 `401(k)` · `401k` 에, `Research, Markets, and Regulations` 는 쉼표를 빼거나 일부만 쓴 표기에도 걸린다.
    # 하이픈·아포스트로피는 넣지 않는다 — `auto-pay` ↔ `Auto pay`, `broker's` ↔ `Broker’s` 를
    # 같게 보려고 버린다. 줄바꿈도 넣지 않는다 — 문장 중간 줄바꿈(pdf 변환 등)에서 용어가 끊긴다.
    re.UNICODE,
)
_GLASCII_WORD_RE = re.compile(r"[A-Za-z]+")

# 모양만 다른 부호를 한 글자로 맞춘다 — 전각 `（` 와 반각 `(`, 한글 문서의 `ㆍ` 와 `·` 는 같은 자리다.
_GLPUNCT_CANON = str.maketrans({
    "，": ",", "、": ",", "；": ";", "：": ":", "。": ".", "！": "!", "？": "?",
    "／": "/", "｜": "|", "ㆍ": "·", "・": "·", "•": "·", "‧": "·",
    "（": "(", "）": ")", "「": "[", "」": "]", "『": "[", "』": "]",
    "《": "<", "》": ">", "〈": "<", "〉": ">", "{": "(", "}": ")",
})


def _GLis_punct(token: str) -> bool:
    """정규화된 토큰이 문장부호 한 글자인가 (`_GLTOKEN_RE` 의 마지막 갈래)."""
    return len(token) == 1 and not token.isalnum()

# ── 한국어 조사 절단 ──────────────────────────────────────────
#
# ## 왜 필요한가 — 하이라이트보다 앞단이 깨져 있었다
#
# 토큰이 `[가-힣]+` 라 `가맹점을` 이 한 덩어리다. 그래서 사전의 `가맹점` 과 매칭되지
# 않았고, 그 실패가 **세 자리에서 서로 다른 얼굴로** 나타났다:
#
# | 방향 | 어디서 깨지나 | 증상 |
# |---|---|---|
# | ko→en | `glexact_match` 가 0건 | **그 용어가 프롬프트에 실리지 않는다** — LLM 은
# |       |                            | "가맹점 → merchant" 를 들은 적이 없다.
# |       |                            | 준수율은 `matched_count=0` 이라 **1.0** 이다 |
# | en→ko | `번역 코드서빙의 `contains_phrase`` 가 False | 번역이 `신용회복위원회를` 로 제대로 옮겼는데
# |       |                            | **준수율 0.0** 이고 양쪽 하이라이트가 안 붙는다 |
#
# 즉 표시 문제가 아니라 **프롬프트·지표·표시가 함께 틀리는** 문제였다.
#
# ## 형태소 분석기는 필요 없다
#
# 이 파일 머리말은 조사 분리를 "형태소 분석기가 필요한 영역" 이라고 적어 두었는데,
# 여기서 필요한 것은 그만큼이 아니다. **사전 용어는 대부분 명사이고 그 뒤에 붙는
# 조사는 닫힌 목록**이라, 영어 `_GLEN_SUFFIX_RULES` 와 같은 구조로 끝난다.
#
# ## 색인이 아니라 **조회할 때** 뗀다
#
# 색인 키에 절단을 걸면 안 된다 — 사전 표제어는 이미 기본형이고, `신용도` 같은 항목이
# `신용` 으로 굳어 **원래 용어가 사라진다.** 문서 쪽 토큰만, 그것도 **정확히 일치하는
# 것을 먼저 찾아보고 없을 때만** 뗀다.
#
# ## 남는 한계 (문서화)
#
# 절단 결과가 2자 이상일 때만 적용하므로 `추가`→`추` 같은 과절단은 막힌다. 다만
# **`신용도` 처럼 3자 이상이면서 조사 글자로 끝나는 용어**는 사전에 `신용` 만 있을 때
# 그쪽으로 걸린다. 사전에 `신용도` 가 함께 있으면 정확 일치가 먼저 이기므로 실무에서
# 문제가 되는 경우는 좁다.
_GLKO_PARTICLES: tuple = (
    # 긴 것부터 — `으로` 를 `로` 보다 먼저 봐야 `으` 가 남지 않는다
    "에게서", "으로는", "에서는", "이라고", "라고는",
    "에게", "에서", "으로", "이라", "라고", "부터", "까지", "마다", "조차",
    "처럼", "만큼", "밖에", "이나", "이란", "로서", "로써", "한테", "보다", "대로",
    "께서", "이며", "이고",
    "은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "도", "만",
    "로", "랑", "야", "아", "나",
)
_GLHANGUL_WORD_RE = re.compile(r"[가-힣]+")

# `-하다` · `-되다` 가 붙은 활용형(`연체되었습니다` · `차환하셨다면`). 조사와 같이 **문서 쪽에서만**
# 떼고, 남는 말이 사전 표제어와 **정확히** 같을 때만 같은 낱말로 본다. 어미는 **통째 목록**으로만
# 맞춘다 — `한`·`할` 로 시작하기만 하면 떼는 식이면 `대출한도`(→`대출`+`한도`)·`상환할인` 같은
# 합성어가 앞 낱말에 걸린다.
_GLKO_PREDICATE_TAILS: tuple = tuple(
    stem + tail
    for stem, tails in (
        ("하", ("다", "는", "여", "여야", "면", "고", "지", "며", "기", "게", "던", "므로", "셨다면",
                "셨습니다", "신", "실", "세요", "십시오", "였다", "였고", "였으며", "였습니다", "였던")),
        ("되", ("다", "는", "어", "어야", "어서", "어도", "면", "고", "지", "며", "기", "게", "던", "므로",
                "셨다면", "신", "었다", "었고", "었으며", "었습니다", "었던", "었으나")),
        ("", ("한다", "한", "할", "함", "합니다", "해", "해야", "해서", "해도", "했다", "했고", "했으며",
              "했습니다", "했던", "했으나", "된다", "된", "될", "됨", "됩니다", "돼", "돼야", "돼서",
              "됐다", "됐고", "됐으며", "됐습니다", "됐던", "됐으나")),
    )
    for tail in tails
)


def _GLstrip_ko_predicate(word: str) -> str:
    """한글 토큰 끝의 `-하다/-되다` 활용 어미를 뗀다. 남는 말이 2자 미만이거나 목록에 없으면 그대로."""
    if not _GLHANGUL_WORD_RE.fullmatch(word):
        return word
    for tail in _GLKO_PREDICATE_TAILS:
        if word.endswith(tail) and len(word) - len(tail) >= 2:
            return word[: -len(tail)]
    return word


def glstrip_ko_particle(word: str, min_stem: int = 2) -> str:
    """한글 토큰 뒤에 붙은 조사를 뗀다. 뗄 수 없으면 **원래 값 그대로** 돌려준다.

    호출부는 "정확히 일치하는 것을 먼저 찾고, 없을 때만" 이 값을 쓴다 (머리말 참고).
    `min_stem` 은 떼고 남아야 할 글자 수다 — 기본 2 가 `추가`→`추` 과절단을 막는다.
    숫자 바로 뒤 낱말(`제3자에게` 의 `자에게`)만 1 로 부른다(`_GLword_eq`).
    """
    if not _GLHANGUL_WORD_RE.fullmatch(word):
        return word
    for particle in _GLKO_PARTICLES:
        if word.endswith(particle) and len(word) - len(particle) >= min_stem:
            return word[: -len(particle)]
    return word


# 영어 동사 활용 어간 후보. 떼고 남는 어간이 3자 미만이면 만들지 않는다 —
# `bed`·`red`·`need`·`sing` 이 엉뚱한 어간으로 사전에 걸리는 것을 막는다.
_GLEN_STEM_MIN = 3


def _GLen_stems(word: str) -> tuple:
    """정규화된 **문서 쪽** 영어 토큰의 동사 활용(-ed/-ing) 어간 후보.

    `refinanced`→(`refinanc`, `refinance`), `transferred`→(…, `transfer`), `applied`→(`apply`,).
    색인 키는 손대지 않는다 — 기본형끼리 깎아 맞추면 `note`·`not` 이 한 키로 합쳐진다.
    """
    if not _GLASCII_WORD_RE.fullmatch(word):
        return ()
    if word.endswith("ied") and len(word) - 3 >= _GLEN_STEM_MIN - 1:
        return (word[:-3] + "y",)
    if word.endswith("ed"):
        stem = word[:-2]
    elif word.endswith("ing"):
        stem = word[:-3]
    else:
        return ()
    if len(stem) < _GLEN_STEM_MIN:
        return ()
    stems = [stem, stem + "e"]
    # 자음 겹침(`transferred`·`billing`) — 하나를 뗀 형태도 본다
    if stem[-1] == stem[-2] and stem[-1] not in "aeiou":
        stems.append(stem[:-1])
    return tuple(stems)


def _GLword_eq(text_token: str, term_token: str, after_digit: bool = False) -> bool:
    """문서 토큰이 사전 토큰과 같은가 — **조사가 붙은 형태·동사 활용형도 같은 것으로 본다.**

    방향이 한쪽이다: 조사·활용은 **문서 쪽에만** 붙는다. `after_digit` 은 표제어에서 이
    낱말 바로 앞이 숫자인 경우(`제3자`)라 조사 절단 하한을 1 로 낮춘다.
    """
    if text_token == term_token:
        return True
    if glstrip_ko_particle(text_token, 1 if after_digit else 2) == term_token:
        return True
    if _GLstrip_ko_predicate(text_token) == term_token:
        return True
    return term_token in _GLen_stems(text_token)


def _GLseq_len(text_tokens: list, start: int, term_tokens: tuple) -> int:
    """`text_tokens[start:]` 가 `term_tokens` 로 시작하면 그 구간의 **문서 토큰 수**, 아니면 0.

    **문서의 부호는 경계**다 — 표제어 낱말 자리에 부호가 오면 맞지 않는다(`mortgage, loan` ≠
    `Mortgage loan`). **표제어의 부호는 표기 습관**이라 자리마다 따로 있어도 없어도 된다
    (`401(k)` ↔ `401k`). 표제어 부호가 문서 부호를 먹는 것은 같은 부호일 때만이다.
    """
    position = start
    for offset, term_token in enumerate(term_tokens):
        text_token = text_tokens[position] if position < len(text_tokens) else None
        if _GLis_punct(term_token):
            if text_token == term_token:
                position += 1
            continue
        if text_token is None or _GLis_punct(text_token):
            return 0
        if not _GLword_eq(
            text_token,
            term_token,
            after_digit=offset > 0 and term_tokens[offset - 1].isdigit(),
        ):
            return 0
        position += 1
    return position - start


def _GLword_len(term_tokens: tuple) -> int:
    """표제어의 낱말 수 — 부호는 세지 않는다. 최장 일치 순서와 길이 상한이 이 값을 쓴다."""
    return sum(1 for token in term_tokens if not _GLis_punct(token))


def _GLcandidate_bucket(index: dict, token: str) -> list:
    """문서 토큰 하나로 열 수 있는 버킷을 합친다 — 정확 일치 · 조사 절단 · 동사 어간 순.

    합친 뒤 길이 내림차순으로 세우되 안정 정렬이라 같은 길이에서는 정확 일치가 앞이다.
    """
    keys = [token]
    for stripped in (glstrip_ko_particle(token), _GLstrip_ko_predicate(token)):
        if stripped != token:
            keys.append(stripped)
    keys.extend(_GLen_stems(token))
    buckets = [index[key] for key in dict.fromkeys(keys) if key in index]
    if len(buckets) <= 1:
        return buckets[0] if buckets else []
    merged = [item for bucket in buckets for item in bucket]
    merged.sort(key=lambda item: _GLword_len(item[0]), reverse=True)
    return merged

# target_lang -> { 정규화된 첫 단어: [(정규화된 전체 단어 튜플, GlossaryTerm), ...] }
# 각 리스트는 단어 수 내림차순 — 같은 첫 단어를 공유하는 후보 중 더 긴 용어
# ("invoice number")가 짧은 용어("invoice")보다 먼저 매칭된다.
_GLINDEX: dict = {}
_GLDISABLED_LANGS: set = set()


def _GLnormalize_en(word: str) -> str:
    """영어 단어를 규칙 기반으로 단수/기본형에 가깝게 정규화한다.

    영어가 아닌 토큰은 소문자화만 하고 통과시킨다 (한국어 조사 분리는 형태소 분석기가
    필요한 영역이며 이 모듈의 책임 범위 밖이다).
    """
    if not _GLASCII_WORD_RE.fullmatch(word):
        return word.lower().translate(_GLPUNCT_CANON)
    lowered = word.lower()
    for suffix, replacement in _GLEN_SUFFIX_RULES:
        # 과교정 방지: 규칙 적용 후 2자 미만이 되면 적용하지 않는다.
        if lowered.endswith(suffix) and len(lowered) - len(suffix) + len(replacement) >= 2:
            return lowered[: -len(suffix)] + replacement
    return lowered


def glload_terms(
    target_lang: str,
    terms: list,
    *,
    max_cached_terms: int = _GLDEFAULT_MAX_CACHED_TERMS,
) -> bool:
    """용어사전을 첫 토큰 역색인으로 메모리에 캐시한다.

    매 번역 요청마다 부르는 함수가 아니다 — 기동 시 1회, 그리고 관리자가
    `POST /glossary/reload` 를 호출할 때만 부른다.

    Returns:
        캐시 성공 여부. False 면 그 언어는 용어사전 없이 번역된다.
    """
    if len(terms) > max_cached_terms:
        _GLINDEX.pop(target_lang, None)
        _GLDISABLED_LANGS.add(target_lang)
        # 3.8절: 용어·언어 값은 메시지에 끼워 넣지 않고 허용 필드로만 남긴다
        gllog_warning(
            "용어 수가 캐시 상한을 초과해 용어사전 적용을 비활성화",
            event="glossary_disabled_over_limit",
            resource_id=f"glossary:{target_lang}",
            item_count=len(terms),
            status="disabled",
        )
        return False

    index: dict = {}
    skipped_long = 0
    for term in terms:
        if not term.term_source or not term.term_source.strip():
            continue
        # 표제어도 **원문과 같은 토큰화**를 탄다. 공백으로만 자르면 `Auto-pay` ·
        # `Broker's` · `401(k)` 가 한 토큰이 되는데 원문은 글자 종류로 잘라
        # `auto`·`pay` 가 되므로 영원히 안 맞는다. 숫자도 토큰이라 `1차` 는 `2차` 와 갈린다.
        normalized = tuple(_GLnormalize_en(word) for word in _GLTOKEN_RE.findall(term.term_source))
        words = [token for token in normalized if not _GLis_punct(token)]
        if not words:
            continue
        # 상한은 낱말 수로 잰다 — 쉼표가 든 기관 이름이 부호 때문에 빠지지 않게
        if len(words) > _GLMAX_TERM_WORDS:
            skipped_long += 1
            continue
        # 색인 키는 첫 **낱말**이다 — 문서에서 표제어의 부호는 빠질 수 있다(`_GLseq_len`)
        index.setdefault(words[0], []).append((normalized, term))

    # 같은 첫 단어 안에서 긴 용어를 먼저 검사 (최장 일치 우선)
    for bucket in index.values():
        bucket.sort(key=lambda item: _GLword_len(item[0]), reverse=True)

    _GLINDEX[target_lang] = index
    _GLDISABLED_LANGS.discard(target_lang)
    gllog_info(
        "용어사전 색인 구성 완료",
        event="glossary_index_built",
        resource_id=f"glossary:{target_lang}",
        item_count=len(terms),
        # 길어서 제외된 항목이 있으면 조용히 넘기지 않는다
        status=f"skipped_long={skipped_long}",
    )
    return True


def glis_disabled(target_lang: str) -> bool:
    """상한 초과로 비활성화된 언어인지 (응답·로그에 노출하기 위한 조회)."""
    return target_lang in _GLDISABLED_LANGS


def glterm_count(target_lang: str) -> int:
    """색인에 올라간 용어 수 (`GET /glossary` 상태 표시용)."""
    return sum(len(bucket) for bucket in _GLINDEX.get(target_lang, {}).values())


def glclear_terms(target_lang: str = None) -> None:
    """캐시 해제. target_lang 이 None 이면 전체를 비운다 (재적재용)."""
    if target_lang is None:
        _GLINDEX.clear()
        _GLDISABLED_LANGS.clear()
    else:
        _GLINDEX.pop(target_lang, None)
        _GLDISABLED_LANGS.discard(target_lang)


def glexact_match(text: str, target_lang: str) -> tuple:
    """활용형(복수형 등)까지 정규화해 사전과 매칭한다.

    첫 토큰 역색인을 쓰므로 사전에 등록된 용어의 최대 단어 수가 커져도 스캔 비용이
    늘지 않는다.

    Returns:
        (매칭된 GlossaryTerm 목록, 매칭 구간이 공백으로 치환된 나머지 텍스트).
        용어 목록은 **(원문, 번역) 쌍 단위로 중복이 제거**돼 있다 — 같은 원문의 다른 후보는
        남아야 한다. 나머지 텍스트는 지금 쓰이지 않는다 — 2단계(임베딩 후보 추출)의 입력이었고,
        2단계를 병합할 때 그대로 쓰려고 계약을 유지한다.
    """
    index = _GLINDEX.get(target_lang)
    if not index or not text:
        return [], text

    tokens = [(m.group(0), m.start(), m.end()) for m in _GLTOKEN_RE.finditer(text)]
    if not tokens:
        return [], text

    normalized_tokens = [_GLnormalize_en(token[0]) for token in tokens]

    found: list = []
    seen: set = set()
    consumed_spans: list = []

    position = 0
    token_count = len(tokens)
    while position < token_count:
        bucket = _GLcandidate_bucket(index, normalized_tokens[position])
        if not bucket:
            position += 1
            continue

        # 한 원문에 후보가 여럿이면(`Account`→계좌 / 계정) **전부** 낸다 — 처음 것에서
        # 멈추면 뒤 후보는 한 번도 나가지 않는다. 같은 표기의 후보는 같은 길이라
        # 버킷(길이 내림차순)에서 이어져 있다.
        matched_len = 0      # 문서 토큰 수 — 다음 스캔 위치
        matched_words = None
        matched_word_len = 0  # 표제어 낱말 수 — 최장 일치 비교
        for normalized_words, term in bucket:  # 긴 후보부터 (최장 일치 우선)
            if matched_words is not None:
                if _GLword_len(normalized_words) < matched_word_len:
                    break
                if normalized_words == matched_words:
                    key = (term.term_source, term.term_target)
                    if key not in seen:
                        seen.add(key)
                        found.append(term)
                continue
            span_len = _GLseq_len(normalized_tokens, position, normalized_words)
            if not span_len:
                continue
            # 키가 (원문, 번역) 쌍이다 — 원문만 보면 같은 원문의 다른 후보가 사라진다
            key = (term.term_source, term.term_target)
            if key not in seen:
                seen.add(key)
                found.append(term)
            consumed_spans.append((tokens[position][1], tokens[position + span_len - 1][2]))
            matched_len = span_len
            matched_words = normalized_words
            matched_word_len = _GLword_len(normalized_words)

        # 매칭된 구간은 건너뛴다 → 같은 토큰이 중복 소비되지 않고 전체가 O(토큰 수)로 유지된다
        position += matched_len if matched_len else 1

    remainder = text
    for start, end in sorted(consumed_spans, reverse=True):
        remainder = remainder[:start] + " " + remainder[end:]

    return found, remainder


# ── glossary_store.py ─────────────────────────────
# 마지막 적재 시도 결과 — `GET /glossary` 와 번역 응답이 함께 본다
_GLLAST_LOAD: dict = {"loaded": False, "reason": "not_loaded", "languages": {}, "source": ""}


# ── 적재: GenOS 독립 용어사전 API ──────────────────────
#
# 응답은 공통 래퍼 `{code, message, data}` 다. 속성은 `data.items`, 용어는
# `data.list`(+ `total_count`)이고 용어 값은 `values = {속성 키: 값}` 이다.
# **이름이 `ko` / `en` 인 속성**을 한국어 · 영어로 읽고(이름이 없으면 키가 같은 속성),
# `ko` 속성이 없으면 대표어(`is_representative`)를 한국어로 쓴다.
#
# 받은 것은 `(한국어, 영어)` 쌍 하나지만 **양방향으로 색인한다** — `ko→en` 과 `en→ko`
# 둘 다 지켜야 하고, 한쪽만 실으면 반대 방향이 "적용 대상인데 색인이 비어" 준수율
# 1.0 으로 나간다(지킬 것이 없다고 보고되는 상태).
#
# **`urllib` 을 쓴다.** MCP 파일은 `requirements.txt` 가 없어 httpx 를 가정할 수 없다.

_GLDEFAULT_API_URL = "https://genos.genon.ai/api/admin"
_GLPAGE_SIZE = 200
_GLMAX_PAGES = 500
_GLFETCH_TIMEOUT = 20.0
_GLKOREAN = "ko"
_GLENGLISH = "en"
_GLSYNONYM = "synonym"

# ── 언어 코드 정규화 ──────────────────────────────────
#
# `target_lang` 은 **색인의 키로 그대로 쓰인다**(`_GLINDEX[target_lang]`). 그래서
# `"KO"`·`"Korean"`·`"한국어"`·`"ko-KR"` 이 오면 색인에 그런 키가 없어
# `language_missing` 으로 떨어졌다 — 예외도 오류도 없이 **용어사전만 조용히 빠진
# 번역**이 나가고, 준수율은 대조할 용어가 없으니 늘 1.0 이라 정상처럼 보인다.
# 화면·워크플로우 변수 표기가 제각각이므로 한 곳에서 흡수한다.
#
# **`genon_lang_policy` 의 표와 같은 내용이어야 한다.** 등록 단위 간 import 이 금지라
# 강제된 사본이고, 갈리면 그쪽이 허용한 값을 이쪽이 못 알아본다 —
# `check_mcp_tools.py` 가 두 파일을 한 네임스페이스에 올려 대조한다.
_GLLANGUAGE_CODES = ("ko", "en", "zh", "th", "vi", "ru")

_GLLANGUAGE_ALIASES = {
    "korean": "ko", "kor": "ko", "ko-kr": "ko", "한국어": "ko", "국문": "ko",
    "english": "en", "eng": "en", "en-us": "en", "영어": "en", "영문": "en",
    "chinese": "zh", "zh-cn": "zh", "zh-hans": "zh", "cn": "zh", "중국어": "zh",
    "thai": "th", "th-th": "th", "태국어": "th",
    "vietnamese": "vi", "vi-vn": "vi", "베트남어": "vi",
    "russian": "ru", "ru-ru": "ru", "러시아어": "ru", "노어": "ru",
}


def glnormalize_lang(value: str) -> str:
    """언어 코드/별칭을 소문자 코드로. **모르는 값은 그대로 돌려준다.**

    거부하지 않는 이유: 이 파일의 계약은 "그 언어에 사전이 있는가" 를 답하는 것이고,
    지원 언어 판정은 `genon_lang_policy.validate_direction` 의 몫이다. 여기서 예외를
    올리면 같은 거부가 두 곳에서 서로 다른 모양으로 나간다.
    """
    normalized = (value or "").strip().lower().replace("_", "-")
    return _GLLANGUAGE_ALIASES.get(normalized, normalized)


class _GLLoadError(Exception):
    """적재를 멈추는 사유. `reason` 이 그대로 `glstatus()["reason"]` 이 된다."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _GLget_data(url: str, token: str):
    """GET 한 번 → 래퍼를 벗긴 `data`. 래퍼 `code` 가 0 이 아니면 실패다."""
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, method="GET")
    request.add_header("Accept", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=_GLFETCH_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _GLLoadError(f"fetch_failed_{exc.code}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _GLLoadError("invalid_response") from exc
    if not isinstance(payload, dict) or payload.get("code") not in (0, None):
        raise _GLLoadError("invalid_response")
    data = payload.get("data")
    return data if data is not None else {}


def _GLfetch(api_url: str, glossary_id: str, token: str) -> tuple:
    """속성 정의와 모든 쪽의 원본 용어 → `(attributes, items)`."""
    import urllib.parse

    base = f"{api_url.rstrip('/')}/data/glossaries/{urllib.parse.quote(glossary_id)}"
    data = _GLget_data(f"{base}/attributes", token)
    attributes = data.get("items") if isinstance(data, dict) else None
    attributes = attributes if isinstance(attributes, list) else []
    items: list = []
    for page in range(1, _GLMAX_PAGES + 1):
        query = urllib.parse.urlencode({"pg": page, "pgSize": _GLPAGE_SIZE})
        data = _GLget_data(f"{base}/terms?{query}", token)
        rows = data.get("list") if isinstance(data, dict) else None
        rows = rows if isinstance(rows, list) else []
        if not rows:
            break
        items.extend(rows)
        total = data.get("total_count")
        if len(rows) < _GLPAGE_SIZE or (isinstance(total, int) and len(items) >= total):
            break
    return attributes, items


def _GLattr_key(attributes: list, name: str) -> str:
    """속성 이름 → 키. 이름이 없으면 키가 같은 속성을 쓴다."""
    for attr in attributes:
        if isinstance(attr, dict) and attr.get("name") == name:
            return str(attr.get("key") or "")
    for attr in attributes:
        if isinstance(attr, dict) and attr.get("key") == name:
            return str(attr.get("key") or "")
    return ""


def _GLresolve_keys(attributes: list, ko_attr: str, en_attr: str, syn_attr: str = "") -> tuple:
    """`(ko 키, en 키, 동의어 키)`. ko 속성이 따로 없으면 대표어를 한국어로 쓴다.

    동의어 속성은 선택이다 — 없으면 키가 빈 문자열이고 동의어 없이 적재한다.
    """
    ko_key = _GLattr_key(attributes, ko_attr) or next(
        (str(a.get("key") or "") for a in attributes
         if isinstance(a, dict) and a.get("is_representative")),
        "",
    )
    syn_key = _GLattr_key(attributes, syn_attr) if syn_attr else ""
    return ko_key, _GLattr_key(attributes, en_attr), syn_key


_GLSYNONYM_SEP = ";"


def _GLtexts(value) -> list:
    """값 → 비어 있지 않은 표기 목록 (순서 유지 · 중복 제거).

    text[] 는 값 **전부**, 문자열은 `;` 로 나눈 전부다. GenOS 는 같은 대표어를 두 번
    등록할 수 없어서 한 한국어의 영어 후보 여럿은 `en` 한 칸에 `;` 로 싣는다 —
    문자열째 쓰면 `mortgage;arm` 이 한 토큰이 되어 그 행 전체가 안 걸린다.
    """
    raw = value if isinstance(value, list) else [value]
    texts: list = []
    for piece in raw:
        for text in str(piece or "").split(_GLSYNONYM_SEP):
            text = text.strip()
            if text and text not in texts:
                texts.append(text)
    return texts


def _GLpairs_from_items(items: list, ko_key: str, en_key: str, syn_key: str = "") -> tuple:
    """원본 용어 → `[(한국어 목록, 영어 목록, 영어 동의어 목록)]` + 걸러진 사유별 건수.

    동의어는 `en` 에 이미 있는 표기를 뺀 나머지다. 동의어만 있고 `en` 이 비면 `en_empty` 다.

    **같은 (한국어, 영어) 쌍만 거른다**(대소문자 무시). 같은 한국어에 영어가 여럿이면
    다 남겨 후보로 싣는다. 항목의 쌍이 전부 앞에서 이미 나왔으면 `duplicate_pair` 로 센다.
    """
    entries: list = []
    seen: set = set()
    skipped: dict = {}
    for item in items:
        values = item.get("values") if isinstance(item, dict) else None
        if not isinstance(values, dict):
            skipped["not_an_object"] = skipped.get("not_an_object", 0) + 1
            continue
        kos, ens = _GLtexts(values.get(ko_key)), _GLtexts(values.get(en_key))
        reason = "ko_empty" if not kos else "en_empty" if not ens else ""
        keys = {(ko.casefold(), en.casefold()) for ko in kos for en in ens}
        if not reason and keys <= seen:
            reason = "duplicate_pair"
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        seen |= keys
        en_folded = {en.casefold() for en in ens}
        syns = [syn for syn in (_GLtexts(values.get(syn_key)) if syn_key else [])
                if syn.casefold() not in en_folded]
        entries.append((kos, ens, syns))
    return entries, skipped


def _GLindex_pairs(entries: list) -> dict:
    """`(한국어 목록, 영어 목록, 영어 동의어 목록)` 항목을 **양방향**으로 색인한다.

    - ko→en: 한국어 표기 **각각**이 영어 전부를 후보로 갖는다. 동의어는 후보가 아니다 —
      프롬프트 지시를 `en` 으로 통일한다(준수 판정은 코드서빙이 동의어까지 본다).
    - en→ko: 영어와 동의어 각각이 **첫 한국어(대표어)만** 후보로 갖는다. 원문에 약어만
      적혀 있어도 걸린다. 뒤의 한국어는 원문에서 찾기 위한 표기 변형이라 출력 후보가 아니다.

    같은 방향 · 같은 쌍은 한 번만 싣는다(항목이 달라도).
    """
    to_english: list = []
    to_korean: list = []
    seen: set = set()

    def _add(terms: list, direction: str, source: str, target: str) -> None:
        key = (direction, source.casefold(), target.casefold())
        if key not in seen:
            seen.add(key)
            terms.append(GLGlossaryTerm(term_source=source, term_target=target))

    for kos, ens, syns in entries:
        for ko in kos:
            for en in ens:
                _add(to_english, _GLENGLISH, ko, en)
        for en in ens + syns:
            _add(to_korean, _GLKOREAN, en, kos[0])
    glload_terms(_GLENGLISH, to_english)
    glload_terms(_GLKOREAN, to_korean)
    return {_GLENGLISH: glterm_count(_GLENGLISH), _GLKOREAN: glterm_count(_GLKOREAN)}


def _GLapi_settings():
    """`(api_url, glossary_id, token, ko_attr, en_attr, syn_attr)` — 용어사전 id 가 비면 `None`.

    경로를 인자로 받지 않는 것과 같은 이유로 **환경변수로 고정한다** — 도구 인자로
    받으면 MCP 를 통해 임의 호스트를 호출하게 된다. 코드서빙 `Config` 와 같은 이름·기본값이다.
    """
    import os

    env = os.environ.get
    api_url = ((env("TRANSLATE_GLOSSARY_API_URL") or "").strip() or _GLDEFAULT_API_URL).rstrip("/")
    glossary_id = (env("TRANSLATE_GLOSSARY_ID") or "").strip()
    token = (env("TRANSLATE_GLOSSARY_TOKEN") or "").strip() or (env("GENOS_TOKEN") or "").strip()
    ko_attr = (env("TRANSLATE_GLOSSARY_KO_ATTR") or "").strip() or _GLKOREAN
    en_attr = (env("TRANSLATE_GLOSSARY_EN_ATTR") or "").strip() or _GLENGLISH
    syn_attr = (env("TRANSLATE_GLOSSARY_SYNONYM_ATTR") or "").strip() or _GLSYNONYM
    if not glossary_id:
        return None
    return api_url, glossary_id, token, ko_attr, en_attr, syn_attr


def _GLfail(reason: str, error_type: str = "") -> dict:
    global _GLLAST_LOAD
    _GLLAST_LOAD = {"loaded": False, "reason": reason, "languages": {}, "source": "api"}
    extra = {"event": "glossary_fetch_failed", "status": f"disabled,reason={reason}"}
    if error_type:
        extra["error_type"] = error_type
    _GLlog.warning("용어사전 조회 실패 — 사전 없이 동작한다", extra=extra)
    return glstatus()


def glload_from_admin_api(
    api_url: str, glossary_id: str, token: str, ko_attr: str = _GLKOREAN, en_attr: str = _GLENGLISH,
    syn_attr: str = _GLSYNONYM,
) -> dict:
    """용어사전 API 에서 받아 양방향으로 색인한다. **예외를 던지지 않는다.**"""
    global _GLLAST_LOAD
    glclear_terms()

    if not (api_url and glossary_id):
        _GLLAST_LOAD = {"loaded": False, "reason": "not_configured", "languages": {}, "source": "api"}
        return glstatus()

    try:
        attributes, items = _GLfetch(api_url, glossary_id, token)
    except _GLLoadError as exc:
        return _GLfail(exc.reason)
    except Exception as exc:  # noqa: BLE001 - 통신 실패 전부. 원문은 남기지 않는다(3.8절)
        return _GLfail("fetch_failed", type(exc).__name__)

    ko_key, en_key, syn_key = _GLresolve_keys(
        attributes, ko_attr or _GLKOREAN, en_attr or _GLENGLISH, syn_attr or _GLSYNONYM
    )
    if not (ko_key and en_key):
        return _GLfail("attribute_not_found")

    pairs, skipped = _GLpairs_from_items(items, ko_key, en_key, syn_key)
    languages = _GLindex_pairs(pairs) if pairs else {}

    _GLLAST_LOAD = {
        "loaded": bool(pairs),
        "reason": "ok" if pairs else "empty",
        "languages": languages,
        "source": "api",
    }
    _GLlog.info(
        "용어사전 적재 완료",
        extra={"event": "glossary_loaded", "item_count": len(pairs),
               "status": f"received={len(items)},skipped={json.dumps(skipped, ensure_ascii=False)}"},
    )
    return glstatus()


def glstatus() -> dict:
    """지금 적재 상태. 번역 응답과 `GET /glossary` 가 같은 값을 본다."""
    return {
        "loaded": _GLLAST_LOAD["loaded"],
        "reason": _GLLAST_LOAD["reason"],
        "languages": dict(_GLLAST_LOAD["languages"]),
        "source": _GLLAST_LOAD.get("source", ""),
    }


def gllanguage_status(target_lang: str) -> dict:
    """특정 언어의 적용 가능 여부 — 번역 응답에 싣는다.

    `disabled_over_limit` 는 사전이 너무 커서 색인을 포기한 상태다. 2단계(벡터 검색)
    폴백이 없으므로 그 언어는 용어사전 없이 번역된다 — 반드시 노출한다.

    **파일 적재 이유와 언어별 이유를 섞지 않는다** (번역 단위 `glossary_store` 와 같은
    규약). 파일이 정상인데 그 언어 항목만 없으면 `language_missing` 이다 — `reason: "ok"`
    를 그대로 쓰면 "적용 안 됨(사유: ok)" 처럼 사유와 상태가 어긋난다.
    """
    if glis_disabled(target_lang):
        return {"available": False, "reason": "disabled_over_limit", "term_count": 0}
    count = glterm_count(target_lang)
    if not count:
        reason = "language_missing" if _GLLAST_LOAD["loaded"] else _GLLAST_LOAD["reason"]
        return {"available": False, "reason": reason, "term_count": 0}
    return {"available": True, "reason": "ok", "term_count": count}


# ── tools.py ─────────────────────────────
class GLToolError(ValueError):
    def __init__(self, error_type: str):
        super().__init__(error_type)
        self.error_type = error_type


_GLMAX_TEXTS = 200
_GLMAX_TEXT_CHARS = 20_000


def _GLtext_arg(arguments: dict, name: str) -> str:
    value = arguments.get(name)
    if value is None:
        raise GLToolError(f"MISSING_ARG_{name.upper()}")
    if not isinstance(value, str):
        raise GLToolError(f"INVALID_TYPE_{name.upper()}")
    return value


def _GLglossary_lookup(arguments: dict) -> dict:
    """문장들에 걸린 사내 용어를 모아 낸다.

    **같은 용어가 여러 문장에 나와도 한 번만** 낸다 — 프롬프트에 실을 목록이라
    중복은 토큰 낭비이고, 호출부가 다시 거르게 하면 그 규칙이 호출부마다 갈린다.
    """
    # 색인 키로 쓰이므로 **여기서 정규화한다** — "KO"·"한국어" 가 오면 사전이 조용히 빠진다.
    target_lang = glnormalize_lang(_GLtext_arg(arguments, "target_lang"))
    texts = arguments.get("texts")
    if not isinstance(texts, list):
        raise GLToolError("INVALID_TYPE_TEXTS")
    if len(texts) > _GLMAX_TEXTS:
        raise GLToolError("TOO_MANY_TEXTS")

    # 이 도구가 쓸 수 있는 상태인지 먼저 본다. 조용히 빈 목록을 주면
    # **"이 문장에 사내 용어가 없다" 와 "사전이 아예 없다" 가 구분되지 않는다.**
    # 2단계(벡터 검색) 폴백이 없어서 후자가 실제로 일어나고, 그때 호출부는 용어사전이
    # 적용된 결과로 착각한다.
    #
    # `is_disabled` 하나만 보면 **상한 초과 한 가지만** 걸러진다 — 사전 미적재(경로
    # 미설정·적재 실패·그 언어 사전 없음)는 전부 `enabled=True` 로 새어 나가 이 도구가
    # 선언한 설명("적재되지 않았거나 상한 초과로 꺼진 언어는 enabled=false")과 어긋난다.
    # `language_status` 가 네 경우를 다 가른다.
    state = gllanguage_status(target_lang)
    if not state.get("available"):
        return {
            # 성공 경로가 `{원문: 번역}` dict 를 주므로 여기서도 dict 다.
            "ok": True, "terms": {}, "candidates": {}, "term_count": 0,
            "enabled": False, "reason": state.get("reason") or "not_loaded",
        }

    # 대소문자 무시한 원문 → (처음 표기, 후보 목록). 매칭이 이미 대소문자를 무시하므로
    # `Account`·`account` 두 행은 한 자리에 함께 걸린다 — 표기 그대로 묶으면 두 줄로 갈린다.
    seen: dict = {}
    for text in texts:
        if not isinstance(text, str):
            raise GLToolError("INVALID_TYPE_TEXTS")
        if len(text) > _GLMAX_TEXT_CHARS:
            raise GLToolError("TOO_LONG_TEXTS")
        matched = glexact_match(text, target_lang)
        # `exact_match` 는 튜플을 돌려준다. 첫 원소가 매칭 용어 목록이다.
        terms = matched[0] if isinstance(matched, tuple) else matched
        for term in terms or []:
            source = getattr(term, "term_source", None)
            target = getattr(term, "term_target", None)
            if not source or not target:
                continue
            _first, candidates = seen.setdefault(source.casefold(), (source, []))
            if target not in candidates:
                candidates.append(target)

    return {
        "ok": True,
        # `{"원문": "번역"}` — **조회 결과**다. 모양은 번역 응답의 `term_map` 과 같지만
        # **의미가 다르므로 UI 하이라이트에 그대로 쓰면 안 된다**:
        # 이건 번역 **전에** "이 문장에 사전 용어가 있다" 를 말하는 값이고,
        # 번역문이 그 용어를 실제로 썼는지는 아직 아무도 모른다. 요구사항의
        # "참고한 단어에 대해서만 표시" 는 번역 **후** 판정이라, 번역 응답의
        # `glossary.term_map`(적용된 것만) 또는 `glossary.hits[].applied` 를 써야 한다.
        # 후보가 여럿이면 ` / ` 로 잇는다(번역 프롬프트 줄 모양과 같다). 목록은 `candidates`.
        "terms": {source: " / ".join(targets) for source, targets in seen.values()},
        "candidates": {source: targets for source, targets in seen.values()},
        "term_count": len(seen),
        "enabled": True,
        "reason": "",
    }


def _GLglossary_status(arguments: dict) -> dict:
    """적재 상태. **호출부가 이 값을 응답에 실어야 한다.**

    2단계 폴백이 없으므로 "사전 없이 번역됨" 이 실제로 일어난다. 그 사실이 드러나지
    않으면 준수율이 낮은 이유를 영영 알 수 없다.
    """
    target_lang = glnormalize_lang(str(arguments.get("target_lang") or ""))
    payload = {"ok": True, "store": dict(glstatus() or {})}
    if target_lang:
        payload["language"] = dict(gllanguage_status(target_lang) or {})
        payload["term_count"] = glterm_count(target_lang)
        payload["disabled"] = glis_disabled(target_lang)
    return payload


def _GLglossary_reload(arguments: dict) -> dict:
    """관리자가 볼륨 파일을 갈아 끼운 뒤 부른다.

    경로는 인자로 받지 않는다 — 임의 경로를 열게 하면 MCP 도구를 통한 파일 읽기가 된다.
    환경변수로 고정된 경로만 다시 읽는다.
    """
    import os

    settings = _GLapi_settings()
    if not settings:
        return {"ok": False, "reason": "api_not_configured"}
    result = glload_from_admin_api(*settings)
    return {"ok": True, "result": dict(result or {})}

# ── 도구 카탈로그는 손으로 적지 않는다 ──────────────────
# `@mcp.tool()` 이 시그니처·타입힌트·독스트링에서 카탈로그를 만든다. 손으로 적은
# JSON-Schema 목록을 따로 두면 노출되는 스키마와 어긋날 수 있다.
# 도구 설명을 고칠 곳은 각 `@mcp.tool()` 함수의 독스트링이다.

_GLHANDLERS = {
    "glossary_lookup": _GLglossary_lookup,
    "glossary_status": _GLglossary_status,
    "glossary_reload": _GLglossary_reload,
}


def glcall_tool(name: str, arguments: dict) -> dict:
    handler = _GLHANDLERS.get(name)
    if handler is None:
        raise GLToolError("UNKNOWN_TOOL")
    return handler(arguments)


# =====================================================================================
# 적재 — **기동 훅이 없으므로 첫 호출에서 한 번 적재한다**
#
# FastAPI 서빙이었을 때는 `lifespan` 이 적재했다. MCP 는 소스 파일 하나를 실행할 뿐
# 기동 훅을 주지 않으므로, 그 자리를 여기가 대신한다.
#
# **import 시점에 적재하지 않는다.** 파일이 크면(수십만 건) 로드가 길어지는데, import 가
# 느리면 서빙이 왜 안 뜨는지 드러나지 않는다. 첫 도구 호출로 미루면 그 지연이 그 호출의
# 지연으로 보인다.
#
# 실패해도 예외를 올리지 않는다 — **용어사전 없이 도는 것이 정상 축퇴 경로**이고,
# 그 사실은 `glossary_status` 로 드러난다.
# =====================================================================================

_GL_LOAD_ATTEMPTED = False


def _gl_ensure_loaded() -> None:
    global _GL_LOAD_ATTEMPTED
    if _GL_LOAD_ATTEMPTED:
        return
    _GL_LOAD_ATTEMPTED = True

    settings = _GLapi_settings()
    if not settings:
        _GLlog.info("용어사전 API 설정 미완료 — 사전 없이 동작한다",
                    extra={"event": "glossary_api_not_configured"})
        return
    try:
        result = glload_from_admin_api(*settings)
    except Exception as exc:  # noqa: BLE001 - 적재 실패가 도구 호출을 막지 않게
        _GLlog.warning("용어사전 적재 실패 — 사전 없이 동작한다",
                       extra={"event": "glossary_load_failed", "error_type": type(exc).__name__})
        return
    # 적재 결과는 언어별 건수(`languages`)로 온다 — `term_count` 라는 키는 없다.
    languages = (result or {}).get("languages") or {}
    total = sum(int(v or 0) for v in languages.values())
    _GLlog.info("용어사전 적재 완료",
                extra={"event": "glossary_loaded", "item_count": total, "status": f"languages={len(languages)}"})


# =====================================================================================
# 로컬 단독 실행 대비: 런타임이 주입하는 전역 `mcp` 가 없으면 최소 shim 을 쓴다.
# =====================================================================================
try:
    mcp  # noqa: F821
except NameError:
    class _GLLocalMCP:
        def tool(self, *args, **kwargs):
            def _decorator(fn):
                return fn
            return _decorator

    mcp = _GLLocalMCP()
    _GLlog.info("로컬 테스트용 shim 사용", extra={"event": "mcp_shim_used"})


# ─────────────────────────────────────────────────────────────
# 디버그 에코 — **테스트 기간 한정**
# ─────────────────────────────────────────────────────────────
# 로그에는 3.8절대로 예외 **클래스명만** 남는다. 도구가 왜 죽었는지(어느 인자에서,
# 무슨 메시지로)는 어디에도 안 남아 원인 추적이 안 된다. 그 동안만 stderr 로 한 줄 더
# 뿜는다 — `print` 가 아니라 **`sys.stderr.write`** 다: stdout 은 MCP 의 전송 채널이라
# 한 줄만 섞여도 프로토콜이 깨진다(`check_deploy_contract` 가 그것을 본다).
# `GENON_DEBUG=1` 일 때만 낸다(기본 꺼짐). 걷어낼 때는 이 블록과 `_gldebug_echo` 호출만 지운다.
_GLDEBUG_MAX_VALUE = 300


def _gldebug_echo(message: str, *, event: str = "", **fields) -> None:
    if (os.environ.get("GENON_DEBUG") or "").strip().lower() not in {"1", "true", "on"}:
        return
    parts = [f"event={event}"] if event else []
    for key, value in fields.items():
        text = str(value)
        if len(text) > _GLDEBUG_MAX_VALUE:
            text = f"{text[:_GLDEBUG_MAX_VALUE]}…(+{len(text) - _GLDEBUG_MAX_VALUE}자)"
        parts.append(f"{key}={text}")
    sys.stderr.write(f"[DEBUG {_GLlog.name}] {message} | {' '.join(parts)}\n")
    sys.stderr.flush()


def _gl_run(name: str, arguments: dict) -> str:
    """도구 본문을 부르고 JSON 문자열로 돌려준다 (적재를 먼저 보장한다)."""
    _gl_ensure_loaded()
    _gldebug_echo(
        "도구 호출",
        event="mcp_tool_called",
        tool=name,
        arg_keys=",".join(sorted(arguments or {})),
    )
    try:
        result = glcall_tool(name, arguments)
    except GLToolError as exc:
        _gldebug_echo(
            "도구 입력 오류", event="mcp_tool_error", tool=name,
            error_type=exc.error_type, exc=repr(exc),
        )
        result = {"ok": False, "error_type": exc.error_type}
    except Exception as exc:  # noqa: BLE001 - 최종 방어선. 원문은 응답에 싣지 않는다 (3.8절)
        _gldebug_echo(
            "도구 실행 실패", event="mcp_tool_failed", tool=name, exc=repr(exc)
        )
        _GLlog.warning("도구 실행 실패", extra={"event": "mcp_tool_failed", "error_type": type(exc).__name__})
        result = {"ok": False, "error_type": "TOOL_EXECUTION_FAILED"}
    return json.dumps(result, ensure_ascii=False)


# =====================================================================================
# 선택지를 **도구 스키마에 싣는다** (`genon_lang_policy` 와 같은 규약)
#
# `target_lang` 이 맨 `str` 이면 **선택지가 계약 어디에도 없다.** 노출되는 스키마에는
# "문자열" 이라고만 적히고, 호출부(캔버스 화면·워크플로우 변수·도구를 고르는 LLM)가
# 자기 목록을 들고 있게 된다. 이 도구에서는 그 결과가 특히 조용하다 —
# 알 수 없는 코드는 오류가 아니라 `enabled=false`(사전 없음)로 떨어지므로,
# **용어사전만 빠진 정상 응답**이 나간다.
#
# 판정은 그대로 본문이 한다(`glnormalize_lang` 이 별칭을 흡수한다). `Literal[...]` 로
# 하지 않는 이유도 같다 — 별칭이 타입 검증에서 죽고, 그러면 "이 언어에는 사전이 없다"
# 는 안내가 전송 실패와 구분되지 않는 형태로 바뀐다.
#
# 빈 문자열(`""`)은 항상 선택지에 넣는다 — GenOS 는 값이 없을 때 `""` 를 주입한다.
# =====================================================================================
try:  # pydantic 은 MCP 런타임(FastMCP)이 스키마를 만들 때 이미 쓰는 패키지다.
    from pydantic import Field as _GLPydanticField
except Exception:  # noqa: BLE001 - 없으면 선택지 없이(맨 str) 동작한다. 판정은 그대로다.
    _GLPydanticField = None


def _GLlang_arg(description: str) -> object:
    """언어 코드 인자에 **선택지가 실린 주석**을 만든다.

    용어사전이 있는 언어(`ko`·`en`)를 설명에 밝히되 **선택지에서 빼지는 않는다** —
    `ru` 로 물어 "이 언어에는 사전이 없다" 는 답을 받는 것이 호출부가 미적용 사유를
    응답에 실을 수 있는 유일한 경로다. 빼면 그 질문 자체를 못 하게 된다.
    """
    values = list(_GLLANGUAGE_CODES) + [""]
    text = (f"{description} 선택지: {', '.join(_GLLANGUAGE_CODES)}. "
            f"사내 용어사전이 있는 언어는 {_GLKOREAN}·{_GLENGLISH} 뿐이고, "
            "나머지는 enabled=false 로 사유가 온다. (미지정은 빈 문자열)")
    if _GLPydanticField is None:
        return str
    return Annotated[str, _GLPydanticField(description=text, json_schema_extra={"enum": values})]


_GLTargetLangArg = _GLlang_arg("번역 대상 언어 코드.")
_GLStatusLangArg = _GLlang_arg("언어별 상태를 볼 때만 지정.")


# =====================================================================================
# MCP Tools
# =====================================================================================

@mcp.tool()
async def glossary_lookup(texts: list | str = "", target_lang: _GLTargetLangArg = "") -> str:
    """[언제 쓰나] 번역·다듬기 프롬프트에 **사내 지정 용어**를 실어야 할 때.

    문장들에 들어 있는 사내 용어와 그 지정 번역을 낸다. 완전 일치 + 영어 활용형
    정규화로 매칭하며, 같은 용어가 여러 문장에 나와도 **한 번만** 낸다.

    Args:
        texts: 검사할 문장들 (최대 200개). JSON 배열 문자열도 받는다.
        target_lang: 번역 대상 언어 코드.

    Returns:
        JSON 문자열 `{"ok", "terms": {원문: 번역}, "candidates": {원문: [번역, …]},
        "term_count", "enabled", "reason"}`. 한 원문에 후보가 여럿이면 `terms` 값은
        `"계좌 / 계정"` 처럼 ` / ` 로 잇고, 문맥에 맞는 하나를 고르게 한다.

        **`enabled=false` 를 반드시 보라.** 사전이 적재되지 않았거나 상한 초과로 꺼진
        언어다. 2단계(벡터 검색) 폴백이 없으므로 그 언어는 **용어사전 없이** 번역되고,
        이 값이 없으면 호출부가 "이 문장에 사내 용어가 없다" 와 구분하지 못한다.

    알려진 한계: 태국어·중국어는 띄어쓰기가 없어 토큰이 길게 잡히므로 사실상 완전 일치만
    걸린다.
    """
    if isinstance(texts, str):
        try:
            texts = json.loads(texts) if texts.strip() else []
        except json.JSONDecodeError:
            return json.dumps(
                {"ok": False, "error_type": "INVALID_TYPE_TEXTS"}, ensure_ascii=False
            )
    return _gl_run("glossary_lookup", {"texts": texts, "target_lang": target_lang})


@mcp.tool()
async def glossary_status(target_lang: _GLStatusLangArg = "") -> str:
    """[언제 쓰나] 번역 응답에 **용어사전이 적용됐는지**를 실어야 할 때.

    Args:
        target_lang: 언어별 상태를 볼 때만 지정. 비우면 전체 적재 상태만 낸다.

    Returns:
        JSON 문자열 `{"ok", "store": {"loaded", "reason", "languages"}, ...}`.
        `target_lang` 을 주면 `language`·`term_count`·`disabled` 가 함께 온다.

        **적재 상태를 숨기지 않는다.** 2단계 폴백이 없어 "사전 없이 번역됨" 이 실제로
        일어나고, 그 사실이 드러나지 않으면 준수율이 낮은 이유를 영영 알 수 없다.
    """
    return _gl_run("glossary_status", {"target_lang": target_lang})


@mcp.tool()
async def glossary_reload() -> str:
    """[언제 쓰나] 관리자가 용어사전에 용어를 등록·수정하고 **승인 결재가 끝난 뒤.**

    **호스트·드라이브를 인자로 받지 않는다** — 도구 인자로 받으면 MCP 를 통해 임의
    호스트를 호출하게 된다. 환경변수로 고정된 드라이브만 다시 받는다.

    Returns:
        JSON 문자열. 설정 미완료면 `{"ok": false, "reason": "api_not_configured"}`.
    """
    return _gl_run("glossary_reload", {})
