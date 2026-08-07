"""용어사전 적재 — 폐쇄망 볼륨의 파일 하나에서 읽는다.

## 왜 파일인가

원본 실험(`genos-glossary`)은 Weaviate 에서 용어를 긁어오는 전제였다. 폐쇄망 벡터DB
가용성이 확인되지 않아 2단계를 보류했으므로(CLAUDE.md), 1단계가 쓸 용어 공급도
벡터DB 에 묶지 않는다. 관리자가 볼륨에 파일을 두면 끝나고, 나중에 Weaviate 가
열리면 `load_from_file` 대신 그쪽에서 읽어 `glossary_exact.load_terms` 를 부르면 된다
(적재 경로만 갈리고 매칭 코드는 그대로다).

## 파일 형식 (둘 다 지원)

`.json` — 언어 코드별 목록. 실무 배포에서 권장한다.
    {"en": [{"source": "매출채권", "target": "accounts receivable", "domain": "회계"}],
     "vi": [...]}

`.csv` — 사내 시스템에서 내보낸 표를 그대로 쓸 때. 헤더 필수.
    target_lang,source,target,domain
    en,매출채권,accounts receivable,회계

## 실패 처리

파일이 없거나 깨졌으면 **용어사전 없이 번역을 계속하되 그 사실을 남긴다.**
번역 자체를 막지 않는 이유: 용어사전은 품질 장치이고, 없다고 번역을 못 하는 것은
아니다. 대신 상태(`status()`)를 응답에 실어 "적용된 줄 알았는데 아니었다"가
생기지 않게 한다 (미측정을 통과로 보이지 않게 하는 저장소 원칙과 같은 계열).
"""

import csv
import json
import os

from translation_pipeline.common.glossary_exact import (
    GlossaryTerm,
    clear_terms,
    is_disabled,
    load_terms,
    term_count,
)
from translation_pipeline.common.logging_utils import log_info, log_warning

# 마지막 적재 시도 결과 — `GET /glossary` 와 번역 응답이 함께 본다
_LAST_LOAD: dict = {"loaded": False, "path": "", "reason": "not_loaded", "languages": {}}


def _rows_from_json(raw: str) -> list:
    """[(lang, source, target, domain)] 로 평탄화."""
    payload = json.loads(raw)
    rows = []
    if isinstance(payload, dict):
        for lang, entries in payload.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, dict):
                    rows.append(
                        (
                            str(lang),
                            str(entry.get("source", "")),
                            str(entry.get("target", "")),
                            str(entry.get("domain", "")),
                        )
                    )
    elif isinstance(payload, list):
        for entry in payload:
            if isinstance(entry, dict):
                rows.append(
                    (
                        str(entry.get("target_lang", "")),
                        str(entry.get("source", "")),
                        str(entry.get("target", "")),
                        str(entry.get("domain", "")),
                    )
                )
    return rows


def _rows_from_csv(path: str) -> list:
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for record in csv.DictReader(handle):
            rows.append(
                (
                    str(record.get("target_lang", "") or ""),
                    str(record.get("source", "") or ""),
                    str(record.get("target", "") or ""),
                    str(record.get("domain", "") or ""),
                )
            )
    return rows


def load_from_file(path: str) -> dict:
    """용어사전 파일을 읽어 언어별로 색인한다.

    Returns:
        상태 dict (`status()` 와 같은 형식). 예외를 던지지 않는다 — 기동 경로에서
        불리므로 파일 문제로 컨테이너가 죽으면 안 된다.
    """
    global _LAST_LOAD
    clear_terms()

    if not path:
        _LAST_LOAD = {"loaded": False, "path": "", "reason": "not_configured", "languages": {}}
        log_info(
            "용어사전 경로 미설정 — 용어사전 없이 번역한다",
            event="glossary_not_configured",
            resource_id="glossary",
            status="disabled",
        )
        return status()

    if not os.path.isfile(path):
        _LAST_LOAD = {"loaded": False, "path": path, "reason": "file_not_found", "languages": {}}
        log_warning(
            "용어사전 파일을 찾지 못했다 — 용어사전 없이 번역한다",
            event="glossary_file_missing",
            resource_id="glossary",
            status="disabled",
        )
        return status()

    try:
        if path.lower().endswith(".csv"):
            rows = _rows_from_csv(path)
        else:
            with open(path, encoding="utf-8") as handle:
                rows = _rows_from_json(handle.read())
    except (OSError, ValueError, csv.Error) as exc:
        # 3.8절: 파일 내용·파싱 예외 원문은 남기지 않고 분류만 남긴다
        _LAST_LOAD = {"loaded": False, "path": path, "reason": "parse_failed", "languages": {}}
        log_warning(
            "용어사전 파일을 해석하지 못했다 — 용어사전 없이 번역한다",
            event="glossary_parse_failed",
            resource_id="glossary",
            error_type=type(exc).__name__,
            status="disabled",
        )
        return status()

    by_lang: dict = {}
    skipped = 0
    for lang, source, target, domain in rows:
        lang = lang.strip().lower()
        source = source.strip()
        target = target.strip()
        if not lang or not source or not target:
            skipped += 1  # 한쪽이 비면 "이 용어는 이렇게 옮긴다"가 성립하지 않는다
            continue
        by_lang.setdefault(lang, []).append(
            GlossaryTerm(term_source=source, term_target=target, domain=domain.strip())
        )

    languages = {}
    for lang, terms in by_lang.items():
        load_terms(lang, terms)
        languages[lang] = term_count(lang)

    _LAST_LOAD = {
        "loaded": bool(languages),
        "path": path,
        "reason": "ok" if languages else "empty",
        "languages": languages,
    }
    log_info(
        "용어사전 적재 완료",
        event="glossary_loaded",
        resource_id="glossary",
        item_count=sum(languages.values()),
        status=f"langs={len(languages)},skipped={skipped}",
    )
    return status()


def status() -> dict:
    """지금 적재 상태. 번역 응답과 `GET /glossary` 가 같은 값을 본다."""
    return {
        "loaded": _LAST_LOAD["loaded"],
        "reason": _LAST_LOAD["reason"],
        "languages": dict(_LAST_LOAD["languages"]),
    }


def language_status(target_lang: str) -> dict:
    """특정 언어의 적용 가능 여부 — 번역 응답에 싣는다.

    `disabled_over_limit` 는 사전이 너무 커서 색인을 포기한 상태다. 2단계(벡터 검색)
    폴백이 없으므로 그 언어는 용어사전 없이 번역된다 — 반드시 노출한다.
    """
    if is_disabled(target_lang):
        return {"available": False, "reason": "disabled_over_limit", "term_count": 0}
    count = term_count(target_lang)
    if not count:
        return {"available": False, "reason": _LAST_LOAD["reason"], "term_count": 0}
    return {"available": True, "reason": "ok", "term_count": count}
