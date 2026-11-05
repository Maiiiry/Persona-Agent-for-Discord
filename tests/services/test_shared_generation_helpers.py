"""共通化した違反通知・出典・JSON 応答の境界を確認する。"""

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from persona_bot.config.constants import BLACKLIST_MAX_VIOLATIONS, MAX_GROUNDING_SOURCES
from persona_bot.services.violation_notice import record_violation_notice
from persona_bot.utils.grounding import normalize_sources
from persona_bot.utils.storage import read_json_response


class SharedHelpersTests(unittest.IsolatedAsyncioTestCase):
    async def test_violation_failure_block_and_duplicate(self):
        for result in (OSError("架空の保存失敗"), (1, False), (BLACKLIST_MAX_VIOLATIONS, True),
                       (BLACKLIST_MAX_VIOLATIONS, False)):
            with self.subTest(result=result):
                record = AsyncMock(side_effect=result if isinstance(result, Exception) else None,
                                   return_value=None if isinstance(result, Exception) else result)
                notice, blocked = await record_violation_notice(SimpleNamespace(record_violation=record), 1, "架空", "警告", blocked_text="以降停止")
                if isinstance(result, Exception):
                    self.assertEqual(notice, "⚠️ 警告")
                elif result[1]:
                    self.assertTrue(blocked)
                    self.assertIn("以降停止", notice)
                elif result[0] == BLACKLIST_MAX_VIOLATIONS:
                    self.assertIsNone(notice)
                else:
                    self.assertIn("あと", notice)

    def test_sources_normalize_before_limit(self):
        items = [{"uri": "  ", "title": "除外"}, {"uri": "  https://example.invalid/1  ", "title": " 題名 "},
                 {"uri": "https://example.invalid/1", "title": "重複"}]
        items.extend({"uri": f"https://example.invalid/{i}", "title": "架空"} for i in range(2, MAX_GROUNDING_SOURCES + 4))
        result = normalize_sources(items)
        self.assertEqual(len(result), MAX_GROUNDING_SOURCES)
        self.assertEqual(result[0], {"uri": "https://example.invalid/1", "title": "題名"})

    def test_json_block_missing_and_required_keys(self):
        blocked = SimpleNamespace(prompt_feedback=SimpleNamespace(block_reason="SAFETY"), text='{"safe": true}')
        self.assertEqual(read_json_response(blocked, required_keys=("safe",))[0], "SAFETY")
        response = SimpleNamespace(prompt_feedback=None, candidates=None, text='{"other": 1}')
        self.assertIsNone(read_json_response(response, required_keys=("safe",))[2])
