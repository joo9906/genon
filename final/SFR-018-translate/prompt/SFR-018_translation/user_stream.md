{#
  스트리밍 번역 유저 프롬프트.

  변수
    text : 문서 조각 하나 (`stream_chunking.split_for_translation` 이 나눈 본문).
           **꼬리 공백은 코드가 떼어 낸다** — LLM 은 응답 끝 공백을 지우므로 그대로
           보내면 문단 경계가 사라진다(`stream_chunking` 머리말).

  머리말을 한 줄만 둔다. 조각 본문이 곧 입력이라 구분선을 넣으면 그것까지 번역문에
  섞여 나올 여지가 생긴다 — 실제로 모델이 구분선을 흉내 내는 경우가 있다.
#}
SOURCE_MARKDOWN:
{{ text }}
