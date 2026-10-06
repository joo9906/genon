# Test/check — 계약·실행 점검 16개

```
python Test/run_all.py            # 점검 16개 + unittest 2벌
python Test/run_all.py mcp_tools  # 이름 일부로 골라 돌린다
```

- 기준 건수는 `Test/run_all.py` 의 `EXPECTED`. 건수가 줄면 FAIL — 실물 경로가 어긋나면 FAIL 없이 건수만 준다.
- 경로는 `paths.py` 한 곳이 안다. 점검별 내용은 각 `check_*.py` 머리말.
- `verify_serving.py` 는 배포한 서빙에 요청을 보내 보는 도구(합계 밖).
- `hwpx_package.py` 는 픽스처 헬퍼, `diagnose_hwpx_markers.py` 는 진단 도구다.
- 코드서빙 단위들은 모듈 이름(`main`·`config`)이 겹쳐 단위마다 subprocess 로 띄운다.
  `check_mcp_tools` 는 반대로 한 네임스페이스에 함께 올려 이름 충돌을 본다.
