{#
  문서 자동 채움 1단계 유저 프롬프트 — 묶음 구성 + 문서 조각.

  변수 (전부 문자열)
    group_names : "본문 k, 요약 k" — 묶음 하나에 한 번씩 들어가는 항목.
    item_names  : "내용 k-j" — 묶음 안에서 늘리는 세부 항목. 없으면 "없음".
    max_topics  : 이 문서에서 받을 주제 수 상한 (남은 묶음 자리).
    chunk_note  : " (3개 구간 중 1번째)" 또는 빈 문자열 — `document_user.md` 와 같다.
    document    : 문서 조각 본문.
#}
[묶음 구성]
- 묶음 항목: {{ group_names }}
- 세부 항목: {{ item_names }}
- 주제는 최대 {{ max_topics }}개까지 씁니다.

[문서 내용]{{ chunk_note }}

{{ document }}

[문서 내용 끝]
위 문서에서 묶음 하나에 들어갈 주제를 문서 순서대로 골라, JSON 객체 하나로 답하십시오.
