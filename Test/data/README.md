# 테스트 데이터 (`Test/data/`)

`Test/onprem/run_*.py` 가 읽는 입력 파일을 놓는 자리다. **저장소에 커밋하지
않는다** — 외부/사내 실제 문서라 라이선스·기밀 문제가 있고, 폐쇄망에서 사람이
직접 옮겨 넣는 것을 전제로 한다(이 저장소가 이미 "이관은 파일이 아니라 사람이
건넌다" 로 정한 것과 같은 규율). 각 하위 폴더는 `.gitkeep` 만 커밋돼 있다.

## hwp 냐 hwpx 냐

이 프로젝트의 hwpx 전용 경로(`/translate/hwpx`·`/generate/upload`·
`final_preprocessor.parse()` 등)는 **`.hwpx`(zip 기반)만** 읽는다. 정부·공공기관
사이트에서 받는 파일은 옛 바이너리 `.hwp` 인 경우가 많다 — 그 경우 한글에서
**다른 이름으로 저장 → hwpx** 로 한 번 변환해야 한다.

## 폴더별 규약

```
Test/data/
  translation/            *.hwpx 아무 이름이나. run_translation.py 가 전부 돈다.
  text_polish/             *.hwpx 아무 이름이나. 내부적으로 markdown 변환 후 폴리시.
  faq/                     *.hwpx 아무 이름이나.
  template_fill/
    sources/               *.hwpx — "이 문서로 템플릿을 채워줘" 할 원본들.
    expected.json          선택. {"파일명.hwpx": {"필드명": "정답값", ...}, ...}
    values.json            선택. {"필드명": "테스트값", ...} — 라운드트립(구조) 검증용.
```

`template_fill` 의 **템플릿 자체는 여기 두지 않는다** — `run_template_fill.py
--template <경로>` 로 실제 사내 템플릿(`{{필드명}}` 슬롯이 있는 hwpx)을 직접
가리킨다. 그 문법은 공공 데이터셋에 없다.

## 어디서 구하나 (외부 데이터셋 후보)

⚠ 정부 사이트에서 받은 파일이 실제로 `.hwpx` 인지, 첨부파일 목록에 무엇이
있는지는 직접 열어 확인할 것 — 아래는 검색으로 찾은 후보이지 다운로드를
보장하지 않는다.

- **서울시 정보소통광장** ([결재문서 목록](https://opengov.seoul.go.kr/sanction/list)) —
  실제 관공서 계획서·보고서 원문. 로그인 불필요, "원문다운로드" 버튼으로 받는다.
  표·다단 구조가 있어 번역/FAQ/글다듬이의 표 격자 회귀에도 좋다.
- **국가법령정보센터** ([law.go.kr](https://www.law.go.kr/)) — 훈령/조례/규정.
  `Test/data`(구 `archive/data`)에 이미 있는 "10·29이태원참사..." 훈령과 같은
  조/항/호 위계 구조 문서를 더 확보할 수 있다.
- **AI Hub** ([aihub.or.kr](https://aihub.or.kr)) — 승인 절차가 있지만 대량·다양한
  텍스트가 필요할 때(번역 병렬 말뭉치, 문서요약 원문, 계약서 텍스트 등). hwpx 가
  아니라 텍스트 원문이 대부분이라, `translation`/`faq`/`text_polish` 에 쓰려면
  hwpx 로 옮겨 담아야 한다(006 자동 채움 소스로도 쓸 수 있다).
