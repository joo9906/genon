# Test/data — 실측 입력 (커밋하지 않는다)

`Test/onprem/run_*.py` 가 읽는다. 폴더마다 `.gitkeep` 만 커밋돼 있다. `.hwp` 는 한글에서 hwpx 로 저장해 넣는다.

```
translation/  text_polish/  faq/     *.hwpx
template_fill/sources/*.hwpx         자동 채움 원본
template_fill/expected.json          선택 {"파일.hwpx": {"필드": "정답"}}
template_fill/values.json            선택 {"필드": "값"} — 라운드트립용
preprocessor/01.pdf                  check_high_preprocessor 가 있으면 쓴다
```

템플릿 자체는 `--template` 으로 직접 가리킨다.
