"""템플릿 파일 저장소 — `TEMPLATE_DIR` 볼륨을 다루는 유일한 곳.

관리자가 올린 hwpx 는 워크플로우 pod(대화)와 코드 서빙 pod(다운로드)가 **공유하는
볼륨**에 놓인다. 그 볼륨을 읽고 쓰는 규칙을 한 파일에 모은다 — 예전에는 경로 검증이
`main.py` 와 `run_chat.py` 에 각각 있었고, 한쪽에만 있는 방어가 생기기 쉬웠다.

여기서 지키는 것:

- **경로 조작 차단.** 템플릿 id 는 파일명이 되므로 `..`·구분자·비허용 문자를 막는다.
  이름 규칙(`_NAME_RE`)이 점을 허용하기 때문에 `..` 은 **따로** 걸러야 한다.
- **blocking I/O 는 전부 스레드로.** 볼륨이 네트워크 스토리지일 수 있고 파일 상한이
  20MB 라, async 핸들러에서 직접 읽으면 그동안 같은 pod 의 다른 요청이 멈춘다 (가이드 6.9).
- **덮어쓰기는 원자적으로.** 임시 파일에 쓰고 `os.replace` 로 바꾼다. 그냥 열어서 쓰면
  덮어쓰는 도중에 다른 요청이 반쪽 파일을 읽는다.
- 실패는 `ApiError` 로 올린다. 호출부마다 "None 이면 404" 를 다시 적지 않게 하기 위해서다.
"""

import asyncio
import os
import re

from .config import Config
from .error_codes import (
    ApiError,
    ERR_API_INPUT,
    ERR_API_INTERNAL,
    ERR_API_TEMPLATE_NOT_FOUND,
)
from .logging_utils import log_error

_SUFFIX = ".hwpx"
# 파일명에 허용할 문자. 한글 템플릿 이름이 기본이라 `가-힣` 을 포함한다.
_NAME_RE = re.compile(r"^[\w\-. ()\[\]가-힣]+$")


def safe_id(raw: str) -> str:
    """등록·삭제·조회에 쓸 템플릿 id 를 검증해 돌려준다.

    Raises:
        ApiError: 비었거나 경로 조작 문자가 있을 때 (400).
    """
    name = (raw or "").strip().removesuffix(_SUFFIX)
    if not name or name.startswith(".") or ".." in name:
        raise ApiError(ERR_API_INPUT, "템플릿 이름에 쓸 수 없는 문자가 있습니다.")
    if any(sep in name for sep in ("/", "\\")):
        raise ApiError(ERR_API_INPUT, "템플릿 이름에 쓸 수 없는 문자가 있습니다.")
    if not _NAME_RE.match(name):
        raise ApiError(ERR_API_INPUT, "템플릿 이름에 쓸 수 없는 문자가 있습니다.")
    return name


def path_for(template_id: str) -> str:
    """저장 경로 (파일이 없어도 만들어 준다 — 등록에 쓴다).

    Raises:
        ApiError: id 가 부적합할 때 (400).
    """
    return os.path.join(Config.TEMPLATE_DIR, f"{safe_id(template_id)}{_SUFFIX}")


def _existing_path(template_id: str) -> str | None:
    """등록돼 있는 템플릿의 경로. 없거나 id 가 부적합하면 None (동기)."""
    try:
        path = path_for(template_id)
    except ApiError:
        return None
    return path if os.path.exists(path) else None


def _read(template_id: str) -> bytes | None:
    path = _existing_path(template_id)
    if path is None:
        return None
    with open(path, "rb") as handle:
        return handle.read()


async def read(template_id: str) -> bytes:
    """등록된 템플릿을 읽는다.

    Raises:
        ApiError: 없을 때 (404).
    """
    payload = await asyncio.to_thread(_read, template_id)
    if payload is None:
        raise ApiError(ERR_API_TEMPLATE_NOT_FOUND)
    return payload


async def exists(template_id: str) -> bool:
    return await asyncio.to_thread(lambda: _existing_path(template_id) is not None)


def _write(target: str, payload: bytes) -> None:
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    tmp_path = f"{target}.tmp"
    with open(tmp_path, "wb") as handle:
        handle.write(payload)
    os.replace(tmp_path, target)  # 원자적 교체 — 반쪽 파일이 읽히지 않게


async def write(template_id: str, payload: bytes) -> None:
    """템플릿 파일을 쓴다 (있으면 덮어쓴다).

    Raises:
        ApiError: 저장 실패 (500). 원인은 로그 메타에만 남긴다 (3.8절).
    """
    target = path_for(template_id)
    try:
        await asyncio.to_thread(_write, target, payload)
    except OSError as exc:
        log_error(
            "템플릿 파일 저장 실패",
            event="template_write_failed",
            resource_id=template_id,
            error_code=ERR_API_INTERNAL.code,
            error_type=type(exc).__name__,
        )
        raise ApiError(ERR_API_INTERNAL, "템플릿을 저장하지 못했습니다.") from exc


async def remove(template_id: str) -> None:
    """템플릿 파일을 지운다.

    Raises:
        ApiError: 없거나(404) 삭제 실패(500).
    """
    path = await asyncio.to_thread(_existing_path, template_id)
    if path is None:
        raise ApiError(ERR_API_TEMPLATE_NOT_FOUND)
    try:
        await asyncio.to_thread(os.remove, path)
    except OSError as exc:
        log_error(
            "템플릿 파일 삭제 실패",
            event="template_delete_failed",
            resource_id=template_id,
            error_code=ERR_API_INTERNAL.code,
            error_type=type(exc).__name__,
        )
        raise ApiError(ERR_API_INTERNAL, "템플릿을 삭제하지 못했습니다.") from exc


def _list_ids() -> list:
    if not os.path.isdir(Config.TEMPLATE_DIR):
        return []
    return sorted(
        os.path.splitext(name)[0]
        for name in os.listdir(Config.TEMPLATE_DIR)
        if name.endswith(_SUFFIX)
    )


async def list_ids() -> list:
    """등록된 템플릿 id 목록. 디렉토리가 없으면 빈 목록.

    디렉토리 순회도 스레드로 뺀다 — 볼륨이 네트워크 스토리지일 수 있다.
    """
    return await asyncio.to_thread(_list_ids)
