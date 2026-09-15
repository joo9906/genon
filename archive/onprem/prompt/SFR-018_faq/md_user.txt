{#
  FAQ 생성 유저 프롬프트 — 마크다운 형식. 문서 본문만 싣는다.

  변수
    document : 조각 하나 (`chunking.split_for_context` 산출물)
    count    : 이 조각의 몫 (시스템 프롬프트와 같은 값, 말미에 한 번 더 못박는다)
#}
문서 내용:
{{ document }}

위 문서 내용만 참고하여 FAQ {{ count }}개를 위 형식대로 출력하세요.
