# Test/onprem — 폐쇄망 실측

실제 LLM 게이트웨이로 `Test/data/<기능>/*.hwpx` 를 네 기능에 태우고 `Test/eval/eval_mcp` 로 채점한다.
assert 없이 `reports/<기능>_<시각>.json` 에 수치만 남긴다. 게이트웨이 설정이 없으면 `CONFIG_MISSING` 으로 끝난다.

```
export GENOS_URL=... LLM_SERVING_ID=... GENOS_TOKEN=...
export REDIS_URL=...                    # 006 만
cd Test/onprem
python run_translation.py --target-lang en
python run_text_polish.py --doc-type email --tone polite
python run_faq.py --count 5
python run_template_fill.py --template <사내 hwpx 템플릿> \
    --admin-token "$TEMPLATE_FILL_ADMIN_TOKEN" --values-json Test/data/template_fill/values.json
```

- 한 프로세스에 기능 하나만 돌린다(`main`/`config` 모듈 이름이 겹친다 — `_harness` 가 막는다).
- `verdict`: `pass` · `fail` · `pass_but_incomplete`(못 잰 기준 있음) · `not_measured`.
