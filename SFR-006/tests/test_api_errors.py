"""오류 응답의 **로그 레벨**이 상태코드로 갈리는지 (2026-08-14 추가).

## 왜 이걸 테스트하나

`error_response` 는 사용자에게 갈 `{error_code, msg}` 를 만들면서 같은 코드를 내부
로그에도 남긴다. 그 레벨이 2026-08-14 까지 **전부 `WARNING`** 이었다 — 잘못된 입력
(4xx, 사용자가 고칠 일)과 내부 오류(5xx, 우리가 고칠 일)가 한 레벨에 섞여 있었고,
**운영이 `level >= ERROR` 로 내부 오류를 거르면 이 단위만 통째로 안 보였다.**
018 세 단위는 내부 오류를 `log_error` 로 남긴다.

응답 본문이 아니라 **레벨**을 보는 이유: 본문은 `check_api_contract` 가 이미 본다.
여기서 지키려는 것은 "같은 사건을 단위마다 같은 레벨로 남긴다" 는 운영 계약이고,
그건 한 줄(`emit = log_error if ... else log_warning`)이면 옛 동작으로 돌아간다.
"""

import io
import logging
import unittest

from . import onprem_path  # noqa: F401 - import 부작용으로 sys.path 를 세운다

from template_fill import api_errors, logging_utils  # noqa: E402
from template_fill.error_codes import (  # noqa: E402
    ERR_API_INPUT,
    ERR_API_INTERNAL,
    ERR_API_TEMPLATE_NOT_FOUND,
)


class ErrorLogLevelTest(unittest.TestCase):
    def setUp(self):
        self.buffer = io.StringIO()
        self.handler = logging.StreamHandler(self.buffer)
        self.handler.setLevel(logging.ERROR)   # ERROR 만 걷어간다 (운영 필터와 같은 모양)
        logging_utils._log.addHandler(self.handler)
        self._level = logging_utils._log.level
        logging_utils._log.setLevel(logging.INFO)

    def tearDown(self):
        logging_utils._log.removeHandler(self.handler)
        logging_utils._log.setLevel(self._level)

    def _emit(self, err) -> str:
        self.buffer.truncate(0)
        self.buffer.seek(0)
        api_errors.error_response(err)
        return self.buffer.getvalue()

    def test_internal_error_is_logged_at_error(self):
        # `event` 는 `extra` 로 가므로 기본 포매터의 출력에는 메시지만 남는다.
        # 여기서 보는 것은 **레벨**이다 — ERROR 핸들러가 걷어갔는가.
        self.assertEqual(ERR_API_INTERNAL.http_status, 500)
        self.assertIn("오류 응답", self._emit(ERR_API_INTERNAL))

    def test_input_error_is_not_logged_at_error(self):
        """4xx 까지 ERROR 로 올리면 반대 방향으로 무너진다 — 사용자 오타가 장애로 보인다."""
        self.assertLess(ERR_API_INPUT.http_status, 500)
        self.assertEqual(self._emit(ERR_API_INPUT), "")

    def test_not_found_is_not_logged_at_error(self):
        self.assertEqual(self._emit(ERR_API_TEMPLATE_NOT_FOUND), "")

    def test_response_body_is_unchanged(self):
        """레벨을 가르는 것이지 응답을 바꾸는 것이 아니다."""
        response = api_errors.error_response(ERR_API_INTERNAL)
        self.assertEqual(response.status_code, ERR_API_INTERNAL.http_status)
        self.assertIn(ERR_API_INTERNAL.code.encode(), response.body)


if __name__ == "__main__":
    unittest.main()
