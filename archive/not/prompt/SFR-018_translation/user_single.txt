{#
  단건 번역 유저 프롬프트.

  변수
    text  : 원문 한 덩어리
    context_line : "CONTEXT (do not translate): <절 제목>\n" 또는 **빈 문자열**.
            문맥은 **배경일 뿐 번역 대상이 아니다.** 배치 경로와 같은 값을 싣는다 —
            폴백에만 빠뜨리면 배치가 실패한 유닛들만 문맥 없이 번역되고, 그 차이는
            배치가 실패했을 때만 드러난다. 빈 문자열일 때 줄이 남지 않도록 **개행까지
            값에 담는다** (`prompt_builder.py` 가 조립한다).
#}
{{ context_line }}SOURCE_TEXT: {{ text }}
