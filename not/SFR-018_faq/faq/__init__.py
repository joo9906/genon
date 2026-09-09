"""SFR-018 FAQ 생성 배포 단위.

두 영역에 걸친다 (SFR-006 과 같은 구성):
- 워크플로우(02) 스텝 — `onprem/workflow/sfr018_faq_0{1,2}_*.py`. 업로드 문서로 FAQ 를
  만들어 채팅에 스트리밍.
- `main.py` `app` — 코드 서빙(03). 재생성·hwpx 직접 파싱·**txt 다운로드**
  (2026-08-12: hwpx/pdf/xlsx 내보내기는 걷어냈다).

다른 배포 단위를 import 하지 않는다 (onprem 규칙). 그래서 `hwpx_text.py` 같은 파일은
SFR-018_translation·SFR-006 에 사본이 있다 — 표 격자 규칙을 고칠 때 함께 본다.
"""
