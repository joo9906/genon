"""번역용 용어사전 RAG 조회 (2단계 구조).

1단계 (glossary_exact.py): 임베딩 없이, 활용형 정규화 기반 정확 매칭.
2단계 (이 파일): 1단계가 못 잡은 나머지 텍스트에서 "단어/구 단위" 후보를 뽑아
                 각각 임베딩한 뒤 Weaviate에서 유사 용어를 검색한다.
                 오탈자, 동의어, 축약형처럼 문자열이 정확히 일치하지 않는 케이스를 커버한다.

GenOS 엔지니어 개발가이드 v1.02 반영
- 10.2절: 임베딩도 Gateway 경로만 사용 (K8s Service DNS 직접 호출 금지)
- 3.6절: connect/read timeout 분리 명시, timeout·5xx만 재시도, 횟수 상한
- 3.8절: 원문/용어 전문은 로그에 남기지 않고 개수·상태만 기록
- 설계 원칙: 이 모듈은 절대 예외를 밖으로 던지지 않는다.
  용어사전 조회 실패가 번역 전체 실패로 전파되면 안 되므로 항상
  "1단계까지의 결과" 또는 빈 리스트로 폴백한다(fail-open).
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

import httpx
import weaviate
from weaviate.auth import AuthApiKey

from config import Config
from translation_pipeline.common.error_codes import (
    ERR_GLOSSARY_EXECUTION,
    ERR_GLOSSARY_UPSTREAM,
)
from translation_pipeline.common.glossary_exact import (
    GlossaryTerm,
    exact_match,
    load_terms,
)
from translation_pipeline.common.logging_utils import log_info, log_warning


@dataclass(frozen=True)
class GlossaryHit:
    term_source: str
    term_target: str
    domain: str = ""
    matched_by: str = "exact"  # "exact" | "vector" - 로깅/디버깅용


# ----------------------------------------------------------------------
# Weaviate / 임베딩 클라이언트 (커넥션 재사용을 위해 모듈 캐시)
# ----------------------------------------------------------------------

_WEAVIATE_CLIENT: "weaviate.WeaviateClient | None" = None
_EMBED_CLIENT: httpx.AsyncClient | None = None


def _get_collection():
    global _WEAVIATE_CLIENT
    if _WEAVIATE_CLIENT is None:
        if not Config.WEAVIATE_URL:
            raise RuntimeError("WEAVIATE_URL이 설정되지 않았습니다.")
        _WEAVIATE_CLIENT = weaviate.connect_to_custom(
            http_host=Config.WEAVIATE_URL,
            http_port=Config.WEAVIATE_HTTP_PORT,
            http_secure=False,
            grpc_host=Config.WEAVIATE_URL,
            grpc_port=Config.WEAVIATE_GRPC_PORT,
            grpc_secure=False,
            auth_credentials=AuthApiKey(Config.weaviate_api_key()),
        )
    return _WEAVIATE_CLIENT.collections.get(Config.GLOSSARY_COLLECTION)


def _resolve_embed_client() -> httpx.AsyncClient:
    global _EMBED_CLIENT
    if _EMBED_CLIENT is None:
        timeout = httpx.Timeout(
            connect=Config.GLOSSARY_CONNECT_TIMEOUT,
            read=Config.GLOSSARY_READ_TIMEOUT,
            write=5.0,
            pool=3.0,
        )
        _EMBED_CLIENT = httpx.AsyncClient(timeout=timeout)
    return _EMBED_CLIENT


async def close_clients() -> None:
    """앱 종료(shutdown) 훅에서 호출. 커넥션 누수를 막는다."""
    global _WEAVIATE_CLIENT, _EMBED_CLIENT
    if _WEAVIATE_CLIENT is not None:
        try:
            _WEAVIATE_CLIENT.close()
        except Exception:  # noqa: BLE001 - 종료 경로는 최선을 다해 정리만 한다
            pass
        _WEAVIATE_CLIENT = None
    if _EMBED_CLIENT is not None:
        await _EMBED_CLIENT.aclose()
        _EMBED_CLIENT = None


# ----------------------------------------------------------------------
# 2단계: 후보 추출 + 배치 임베딩 + 유사 검색
# ----------------------------------------------------------------------

_STOPWORDS_EN = {"the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "is", "are"}
_TOKEN_RE = re.compile(r"[A-Za-z]+|[가-힣]+", re.UNICODE)


def _extract_candidates(text: str, max_candidates: int) -> list[str]:
    """1단계에서 못 잡은 나머지 텍스트에서 용어 후보(단어/2-gram)를 뽑는다.

    문장 전체가 아니라 '개별 용어가 될 만한 조각'만 임베딩 대상으로 삼아야
    임베딩 벡터에 개별 용어의 신호가 희석되지 않는다.
    """
    tokens = [t for t in _TOKEN_RE.findall(text) if len(t) >= 2 and t.lower() not in _STOPWORDS_EN]
    if not tokens:
        return []
    bigrams = [f"{tokens[i]} {tokens[i + 1]}" for i in range(len(tokens) - 1)]
    candidates = list(dict.fromkeys(tokens + bigrams))  # 순서를 유지한 채 중복 제거
    return candidates[:max_candidates]  # 비용 상한


async def _embed_batch(candidates: list[str]) -> list[list[float]] | None:
    """여러 후보를 한 번의 API 호출로 임베딩한다 (embeddings 엔드포인트는 input 리스트를 지원).

    Returns:
        후보 순서와 동일하게 정렬된 임베딩 벡터 목록. 실패 시 None (예외를 던지지 않음).
    """
    if not candidates:
        return []
    if not Config.GENOS_URL or not Config.EMBEDDING_SERVING_ID:
        log_warning("[GLOSSARY] 임베딩 설정(GENOS_URL/EMBEDDING_SERVING_ID) 누락 → 2단계 스킵")
        return None

    url = f"{Config.GENOS_URL}/api/gateway/rep/serving/{Config.EMBEDDING_SERVING_ID}/v1/embeddings"
    headers = {"Authorization": f"Bearer {Config.genos_token()}"}
    client = _resolve_embed_client()
    retry_count = max(1, Config.GLOSSARY_RETRY_COUNT)

    for attempt in range(retry_count):
        try:
            resp = await client.post(url, headers=headers, json={"input": candidates})
            resp.raise_for_status()
            data = sorted(resp.json()["data"], key=lambda d: d.get("index", 0))
            return [d["embedding"] for d in data]
        except httpx.TimeoutException as exc:
            if attempt < retry_count - 1:
                await asyncio.sleep(0.3 * (attempt + 1))
                continue
            log_warning(
                f"[GLOSSARY 임베딩 실패] error_code={ERR_GLOSSARY_UPSTREAM.code} "
                f"error_type={type(exc).__name__} {retry_count}회 재시도 후 포기"
            )
            return None
        except httpx.HTTPStatusError as exc:
            retryable = exc.response.status_code >= 500
            if retryable and attempt < retry_count - 1:
                await asyncio.sleep(0.3 * (attempt + 1))
                continue
            code = ERR_GLOSSARY_UPSTREAM.code if retryable else ERR_GLOSSARY_EXECUTION.code
            log_warning(
                f"[GLOSSARY 임베딩 실패] error_code={code} "
                f"upstream_status={exc.response.status_code}"
            )
            return None
        except Exception as exc:  # noqa: BLE001 - 최종 방어선
            log_warning(
                f"[GLOSSARY 임베딩 실패] error_code={ERR_GLOSSARY_EXECUTION.code} "
                f"error_type={type(exc).__name__}"
            )
            return None
    return None


def _hybrid_search_sync(vector: list[float], query_text: str, topk: int, alpha: float) -> list[dict]:
    """weaviate-client는 동기 클라이언트이므로 asyncio.to_thread로 감싸서 호출한다."""
    collection = _get_collection()
    response = collection.query.hybrid(
        query=query_text,
        vector=vector,
        alpha=alpha,
        limit=topk,
        return_metadata=["score"],
    )
    results = []
    for obj in response.objects:
        props = dict(obj.properties)
        score = getattr(obj.metadata, "score", None) if obj.metadata else None
        props["_score"] = score if score is not None else 0.0
        results.append(props)
    return results


async def _vector_lookup(
    sem: asyncio.Semaphore,
    remainder_text: str,
    target_lang: str,
    already_matched: set[str],
) -> list[GlossaryHit]:
    """2단계: 후보 span만 뽑아 임베딩 → 유사 용어 검색. 실패하면 조용히 빈 리스트."""
    candidates = _extract_candidates(remainder_text, Config.GLOSSARY_MAX_CANDIDATES)
    if not candidates:
        return []

    async with sem:
        vectors = await _embed_batch(candidates)
        if not vectors:
            return []

        try:
            search_results = await asyncio.gather(*[
                asyncio.to_thread(
                    _hybrid_search_sync, vec, cand, Config.GLOSSARY_TOPK, Config.GLOSSARY_ALPHA
                )
                for cand, vec in zip(candidates, vectors)
            ])
        except Exception as exc:  # noqa: BLE001
            log_warning(
                f"[GLOSSARY 검색 실패] error_code={ERR_GLOSSARY_EXECUTION.code} "
                f"error_type={type(exc).__name__}"
            )
            return []

    hits: list[GlossaryHit] = []
    for raw in search_results:
        for props in raw:
            term_source = str(props.get("term_source", "")).strip()
            term_target = str(props.get("term_target", "")).strip()
            prop_lang = str(props.get("target_lang", "")).strip().lower()
            score = float(props.get("_score", 0.0) or 0.0)

            if not term_source or not term_target or term_source in already_matched:
                continue
            if prop_lang and prop_lang != target_lang.lower():
                continue
            if score < Config.GLOSSARY_MIN_SCORE:
                continue  # 오탐 방지용 최소 유사도 컷

            already_matched.add(term_source)
            hits.append(
                GlossaryHit(term_source, term_target, str(props.get("domain", "")), matched_by="vector")
            )

    return hits


# ----------------------------------------------------------------------
# 공개 진입점
# ----------------------------------------------------------------------

async def lookup_glossary_terms(
    sem: asyncio.Semaphore,
    batch_texts: list[str],
    target_lang: str,
) -> list[GlossaryHit]:
    """배치 원문들을 대상으로 용어사전에서 관련 용어를 찾는다 (1단계 정확 매칭 + 2단계 유사 검색).

    Args:
        sem: 2단계(임베딩/Weaviate) 조회 동시성 제어 세마포어. LLM 세마포어와 분리해서 넘겨야
            번역 동시성과 용어사전 조회 동시성이 서로 발목 잡지 않는다.
        batch_texts: 이번 번역 배치에 포함된 원문 텍스트 목록.
        target_lang: 번역 대상 언어 코드.

    Returns:
        원문에 실제로 등장하거나(1단계) 충분히 유사한(2단계, 스코어 컷 통과) 용어만
        담긴 GlossaryHit 목록. 두 단계 모두 실패해도 예외를 던지지 않고 빈 리스트를 반환한다.
    """
    combined = "\n".join(t for t in batch_texts if t.strip())
    if not combined.strip():
        return []

    # 1단계: 정확 매칭 (임베딩/네트워크 호출 없음 - 실패 지점 자체가 없다)
    exact_terms, remainder = exact_match(combined, target_lang)
    hits: list[GlossaryHit] = [
        GlossaryHit(t.term_source, t.term_target, t.domain, matched_by="exact") for t in exact_terms
    ]

    # 2단계: 나머지에서 후보만 추출해 유사 매칭. 실패해도 1단계 결과는 그대로 살린다.
    already_matched = {h.term_source for h in hits}
    try:
        vector_hits = await _vector_lookup(sem, remainder, target_lang, already_matched)
        hits.extend(vector_hits)
    except Exception as exc:  # noqa: BLE001 - 최종 방어선, 여기서도 절대 전파하지 않는다
        log_warning(
            f"[GLOSSARY 2단계 실패] error_code={ERR_GLOSSARY_EXECUTION.code} "
            f"error_type={type(exc).__name__}"
        )

    log_info(
        f"[GLOSSARY] 정확매칭 {len(exact_terms)}건 + 유사매칭 {len(hits) - len(exact_terms)}건 "
        f"(target_lang={target_lang})"
    )
    return hits


# ----------------------------------------------------------------------
# 용어사전 전체 캐시 갱신 (1단계용) - 서버 시작 시 / 주기적으로 호출
# ----------------------------------------------------------------------

def _fetch_all_terms_sync(target_lang: str) -> list[GlossaryTerm]:
    """Weaviate에서 특정 언어의 용어 전체를 커서 방식으로 긁어온다.

    성능상 반드시 지켜야 할 두 가지:
    1) target_lang 필터를 Weaviate 서버측 filter로 넘긴다. 파이썬에서 필터링하면
       GLOSSARY_TARGET_LANGS가 3개일 때 전체 컬렉션을 3번 풀스캔하게 된다.
    2) return_properties로 필요한 4개 프로퍼티만 가져온다. 기본값은 전체 프로퍼티를
       가져오므로 definition 같은 긴 텍스트 필드까지 전송되어 네트워크/메모리가 낭비된다.
       벡터는 애초에 받지 않는다(1단계는 문자열 매칭만 하므로 불필요).
    """
    collection = _get_collection()
    terms: list[GlossaryTerm] = []
    iterator = collection.iterator(
        return_properties=["term_source", "term_target", "target_lang", "domain"],
        include_vector=False,
    )
    for obj in iterator:
        props = obj.properties
        # 서버측 필터가 적용됐더라도 대소문자 표기 편차가 있을 수 있어 한 번 더 확인한다.
        if str(props.get("target_lang", "")).strip().lower() != target_lang.lower():
            continue
        term_source = str(props.get("term_source", "") or "").strip()
        term_target = str(props.get("term_target", "") or "").strip()
        if not term_source or not term_target:
            continue
        terms.append(GlossaryTerm(term_source, term_target, str(props.get("domain", "") or "")))
        # 안전 상한: 컬렉션 지정을 잘못해 문서 청크 컬렉션을 순회하는 사고를 대비해
        # 하드 컷을 둔다. 여기 걸리면 캐시 상한 로직이 1단계를 비활성화한다.
        if len(terms) > Config.GLOSSARY_MAX_CACHED_TERMS:
            log_warning(
                f"[GLOSSARY] fetch 상한 초과 -> 조회 중단: target_lang={target_lang} "
                f"item_count={len(terms)} (collection={Config.GLOSSARY_COLLECTION} 확인 필요)"
            )
            break
    return terms


async def refresh_glossary_cache(target_langs: list[str]) -> None:
    """용어사전 전체를 언어별로 읽어와 1단계(정확 매칭) 캐시를 갱신한다.

    실패해도 예외를 던지지 않는다 — 갱신 실패 시 이전 캐시(또는 빈 캐시)로
    계속 서비스하며, 다음 주기에 재시도한다 (fail-open).
    """
    for lang in target_langs:
        try:
            terms = await asyncio.to_thread(_fetch_all_terms_sync, lang)
            # load_terms는 상한 초과 시 False를 반환하고 1단계를 비활성화한다(OOM 대신 degradation).
            cached = load_terms(lang, terms, max_cached_terms=Config.GLOSSARY_MAX_CACHED_TERMS)
            log_info(
                f"[GLOSSARY] 캐시 갱신 완료: target_lang={lang} "
                f"item_count={len(terms)} stage1_enabled={cached}"
            )
        except Exception as exc:  # noqa: BLE001
            log_warning(
                f"[GLOSSARY 캐시 갱신 실패] error_code={ERR_GLOSSARY_EXECUTION.code} "
                f"target_lang={lang} error_type={type(exc).__name__}"
            )


async def start_periodic_refresh(target_langs: list[str], interval_sec: int) -> None:
    """FastAPI 백그라운드 태스크로 등록해 주기적으로 캐시를 갱신한다. main.py에서 시작/취소한다."""
    await refresh_glossary_cache(target_langs)  # 최초 1회는 즉시
    while True:
        await asyncio.sleep(interval_sec)
        await refresh_glossary_cache(target_langs)
