# WIP — 톤 프롬프트를 **동적으로** 가져온다 (착수 전)

> **지금은 코드 하드매칭이다** (2026-09-03). 이 문서는 "다음에 무엇을 하면 되나" 만
> 적어 둔 것이고, 코드는 한 줄도 안 들어가 있다.

## 1. 지금 어떻게 도나

톤마다 다른 시스템 프롬프트를 GenOS 프롬프트 라이브러리에서 받는다.

```
config.TONE_PROMPT_IDS = {}                    # ← 온프레미스에서 만든 ID 를 여기 적는다
config.TONE_PROMPT_NAME_FORMAT = "system_{tone}"
```

- `Config.prompt_ids_raw()` 가 **코드 맵을 앞, 환경변수(`POLISH_PROMPT_IDS`)를 뒤**에
  놓고 이어 붙인다 — `prompt_library.prompt_ids()` 가 순서대로 덮으므로 **환경변수가
  이긴다.** 고객사마다 ID 가 달라도 재배포 없이 등록 화면에서 바꿀 수 있다.
- `main._tone_prompt_name(tone_key)` 이 **라이브러리에 본문이 실제로 있을 때만** 그
  이름을 쓴다. 없으면 `"system"` 으로 떨어져 `system.j2` + `tone_instruction` 으로 돈다.
- 그물: `check_unit_endpoints` 의 "글다듬이 톤 전용 프롬프트를 고른다" ·
  "등록 안 된 톤은 system 으로 떨어진다" 2건.

## 2. 무엇이 아쉬운가

**관리자가 톤을 추가하면 그 톤의 전용 프롬프트를 받을 수 없다.** 톤 목록 자체는 이미
동적이다(관리자 정책 JSON, `POLISH_POLICY_PROMPT_ID`) — 그런데 **톤 → 프롬프트 대응만
코드에 있다.** 그래서 새 톤은 내장 `system.j2` + 정책이 준 `tone_instruction` 으로만 돈다.

**이 상태가 조용하다는 것이 요점이다.** 오류가 나지 않고 결과물도 그럴듯하게 나온다 —
관리자는 자기가 만든 톤 전용 프롬프트가 안 쓰이는 줄 모른다.

## 3. 어떻게 붙이나

**톤 정책 JSON 에 프롬프트를 함께 적게 한다.** 목록과 대응을 한 항목에서 내면 갈리지 않는다.

```json
{"tones": [
  {"code": "urgent", "label": "긴급·통보", "instruction": "…", "prompt_id": "57"}
]}
```

- **고칠 자리는 파서 2벌이다** — 글다듬이 `policy_store.parse_policy_document` 와
  MCP `lpparse_policy_document`. `check_tone_policy` 가 **같은 입력을 두 파서에 태워**
  대조하므로 한쪽만 고치면 걸린다.
- `TonePreset` 에 `prompt_id`(또는 `prompt_name`) 필드를 더하고, `_tone_prompt_name`
  이 **정책값 → 코드 맵 → `"system"`** 순으로 고르게 한다.
- `Config.prompt_ids_raw()` 에 정책에서 온 ID 를 얹어야 `prompt_library` 가 그 이름을
  받아 온다. **`prompt_library.py` 는 네 단위 사본이 본문까지 같아야 하므로 손대지
  않는다**(`check_deploy_contract.check_prompt_library_copies`) — 얹는 자리는
  글다듬이 `config.py` 다.
- **TTL 이 둘이라 겹친다** — 정책 60초, 프롬프트 60초. 정책이 먼저 갱신되고 프롬프트가
  아직 옛 캐시면 **새 톤이 한 텀 동안 `system` 으로 떨어진다.** `POST /policies/reload`
  와 `POST /prompts/reload` 를 함께 부르게 하거나, 정책 리로드가 프롬프트 캐시도
  비우게 한다.

## 4. 안 할 것

- **ID 를 코드에 최종적으로 박아 두지 않는다** — 지금 코드 맵은 "온프레미스에서 만든 뒤
  적어 두는 자리" 이지 배포 산출물이 아니다(§10.5).
- **eval 은 따라오지 않는다.** 새 톤의 종결어미·금지 표현은 `eval_mcp/tone_metrics.py`
  의 `TONE_RULES` 에 넣기 전까지 `skipped` 로 드러난다 — 그것이 규약이다(통과로 세지 않는다).
