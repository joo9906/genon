# SFR-006 — 회귀 테스트 (구현은 `onprem/` 에 있다)

> **이 디렉토리에는 구현이 없다.** 2026-08-11 부터 테스트 전용이다.
> 실행 코드는 전부 `onprem/codeserving/SFR-006_template_fill/` 와
> `onprem/workflow/sfr006_0*.py` 에 있다.

## 왜 사본을 없앴나

예전에는 여기에 `template_fill/` 구현 **사본**이 있었고 `tests/` 가 그 사본을 검증했다.
사본은 자동 동기화되지 않으므로 **운영 코드를 고쳐도 테스트는 옛 코드를 통과시켰다.**
말로만 있던 위험이 아니라 실제로 갈려 있었다:

| 사본에만 있던 것 | 실제 |
|---|---|
| `field_judge.mock_extract` | onprem 에 없다 — 배포 단위에 mock 경로를 두지 않는 규칙이라 존재한 적이 없다. **운영에 없는 코드를 지키는 테스트였다** |
| `hwpx_fields.scan_tokens` | 슬롯 문법 전환(2026-08-06)으로 없어졌다 |
| `parse_updates -> (dict, list)` | 지금은 `ParsedIntent` 를 돌려준다 (수정·삭제·본문 추가가 한 응답에 섞여 와서 튜플로는 못 담는다) |
| 파일 기반 `session_store` (`Config.SESSION_DIR`) | Redis 로 옮겼다 — 레플리카가 둘이면 파일 세션은 깨진다 |
| `run_chat.run` 멀티턴 generator | 워크플로우 스텝 3개 + `chat_api` 로 갈렸다 |

그래서 사본을 지우고 **테스트가 onprem 을 직접 태우게** 했다. 이제 테스트가 깨지면
그것은 운영 코드가 바뀐 것이고, 그게 회귀 테스트가 해야 할 일이다.

## 구성

```
tests/
  onprem_path.py        ⭐ onprem 단위 경로를 sys.path 에 세운다 — 경로를 아는 유일한 자리
  fixtures.py           합성 hwpx (누름틀 픽스처 + 슬롯 픽스처)
  test_field_judge.py   LLM 응답 화이트리스트 검증·기각·수정/삭제 충돌 해소
  test_hwpx_fields.py   스캔·채우기 라운드트립 (누름틀 폴백 + **슬롯 기본 경로**)
  test_session_store.py Redis 세션 왕복·키 안전·블록 보존 (가짜 Redis)
hwpx.py                 (레거시) {{token}} 방식 로컬 검증 CLI — onprem 에 대응물이 없어 남겨 둔다
```

`onprem_path.py` 가 경로를 아는 **유일한 자리**다. 재배치(2026-08-11)로 단위가
`onprem/codeserving/` 아래로 내려갔을 때 옛 `smoke/fixture.py` 가 경로를 따로 들고 있어
**스모크 6개가 전부 죽어 있었고 아무도 몰랐다.** 경로를 파일마다 적으면 다음 이동 때
같은 일이 반복된다.

## 실행

```
cd SFR-006 && python -m unittest discover -s tests -t .
```

서버·Redis·LLM·한/글·샘플 hwpx 전부 불필요하다. 픽스처를 메모리에서 만든다.
Windows 콘솔에서는 `PYTHONIOENCODING=utf-8` 을 준다 (cp949 가 `—` 에서 죽는다).

## 무엇을 여기서 보고, 무엇을 `onprem/test/` 에서 보나

경계는 **"단위 하나의 함수인가, 여러 영역에 걸친 계약인가"** 다.

| 여기(`SFR-006/tests`) | `onprem/test/` |
|---|---|
| 파서·검증기 같은 **함수 단위 동작** | 배포 계약, 엔드포인트 한 바퀴, 영역 간 계약 |
| `unittest` (assert 로 실패를 낸다) | 점검 스크립트 (OK/FAIL 표를 찍는다) |
| — | 대화 한 턴(`check_chat_turn`), 문단 복제(`check_body_blocks`), 사본 대조(`check_table_grid`·`check_tone_policy`) |

겹치지 않게 나눈다. 예컨대 채팅 흐름은 `check_chat_turn.py`(22건)가 02 스텝 3개와 03
`chat_api` 를 **함께** 태워 보므로 여기서 다시 하지 않는다.

## 없앤 것과 그 자리를 대신하는 것

`smoke/` 6개는 지웠다. 재배치 이후 **전부 `ModuleNotFoundError` 로 죽어 있었고**,
살려 봐도 옛 설계(라벨 방식·`run_chat`·`collect_style_specs`)를 전제해 통과하지 못한다.
각각의 자리는 이미 채워져 있다:

| 없앤 스모크 | 지금 그 자리 |
|---|---|
| `smoke_api.py` | `onprem/test/check_api_contract.py` (42건) |
| `smoke_chat_edit.py`·`smoke_crosspath.py` | `onprem/test/check_chat_turn.py` (22건) |
| `smoke_direct_edit.py` | `check_api_contract.py` 의 `PATCH`/`DELETE /values` |
| `smoke_markdown.py` | `onprem/test/check_table_grid.py` (표 격자 4벌 대조) |
| `smoke_real.py` | 대응 없음 — 커밋되지 않은 실물 `data/파워.hwpx` 를 요구해서 어차피 CI 에서 못 돈다 |

되살릴 일이 생기면 `git show HEAD:SFR-006/smoke/smoke_api.py` 로 꺼낸다.
