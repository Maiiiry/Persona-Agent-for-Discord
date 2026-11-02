"""DB障害時の案内・実際の保存状態・パネルからの再試行を検証する。"""

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from persona_bot.core.database import Database
from persona_bot.services.reminder_service import ReminderService, ReminderStorageError
from persona_bot.services.stats_service import StatsService
from persona_bot.views.functions_view import ReminderButton
from persona_bot.views.reminder_view import ReminderCancelSelect, ReminderView
from persona_bot.views.stats_privacy_view import StatsPrivacyConfirmButton, StatsPrivacyView
from persona_bot.views.view_parts import PanelView


def make_interaction():
    return SimpleNamespace(
        user=SimpleNamespace(id=11), extras={},
        response=SimpleNamespace(defer=AsyncMock()),
        edit_original_response=AsyncMock(), original_response=AsyncMock(),
        followup=SimpleNamespace(send=AsyncMock()),
    )


class StorageFailureNoticeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        directory = tempfile.TemporaryDirectory(prefix="storage-notice-test-")
        self.addCleanup(directory.cleanup)
        self.db = Database(Path(directory.name) / "bot.db")
        self.db.initialize()
        self.addCleanup(self.db.close)
        self.reminders = ReminderService(None, self.db, None)
        self.when = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def add_reminder(self):
        return self.db.reminder_add(
            user_id="11", user_name="架空の本人", guild_id=1, channel_id=2,
            message="架空の予定", remind_at="2026-01-02T00:00:00+00:00",
            created_at=self.when.isoformat(),
        )

    def make_hub_button(self):
        # 一覧ボタンは実物を使い、他の機能サービスは起動しない。
        hub = PanelView(timeout_notice="架空の時間切れ案内")
        hub.reminders = self.reminders
        hub.clone = lambda: hub
        button = ReminderButton()
        hub.add_item(button)
        self.addCleanup(hub.stop)
        return hub, button

    async def test_stats_failure_and_success_match_next_record_for_stop_and_resume(self):
        for initially_opted_out in (False, True):
            for save_fails in (True, False):
                with self.subTest(initially_opted_out=initially_opted_out, save_fails=save_fails):
                    with patch("persona_bot.services.stats_service.resolve_timezone", return_value=timezone.utc):
                        stats = StatsService(self.db, SimpleNamespace(generate=AsyncMock()))
                    entry = stats._new_entry("架空の本人")
                    entry.update(total_count=1, opt_out=initially_opted_out)
                    self.db.stats_save_user("11", entry)
                    stats.cache["11"] = entry
                    view = StatsPrivacyView(stats, viewer_id="11", viewer_name="架空の本人")
                    self.addCleanup(view.stop)
                    view.temp_collect_enabled = initially_opted_out
                    button = next(item for item in view.children if isinstance(item, StatsPrivacyConfirmButton))
                    interaction = make_interaction()
                    if save_fails:
                        with patch.object(self.db, "stats_save_user", side_effect=sqlite3.OperationalError("架空のDB障害")), self.assertLogs("persona_bot.services.stats_service", level="ERROR"):
                            await button.callback(interaction)
                    else:
                        await button.callback(interaction)
                    notice = interaction.edit_original_response.call_args.kwargs["content"]
                    expected_opt_out = initially_opted_out if save_fails else not initially_opted_out
                    if save_fails:
                        self.assertIn("設定は変更されていません", notice)
                        self.assertIn("再度", notice)
                        self.assertNotIn("停止しました", notice)
                        self.assertNotIn("再開しました", notice)
                        self.assertNotIn("再起動", notice)
                    else:
                        self.assertIn("停止しました" if expected_opt_out else "再開しました", notice)
                    self.assertEqual(stats.is_opted_out("11"), expected_opt_out)
                    await stats.record("11", "架空の本人", "架空の追加発言", self.when)
                    persisted = self.db.stats_load_all()["11"]
                    self.assertEqual(persisted["opt_out"], expected_opt_out)
                    self.assertEqual(persisted["total_count"], 1 if expected_opt_out else 2)

    async def test_list_db_failure_keeps_hub_and_retry_loads_pending_record(self):
        reminder_id = self.add_reminder()
        hub, button = self.make_hub_button()
        interaction = make_interaction()
        with patch.object(self.db, "reminder_list_pending", side_effect=sqlite3.OperationalError("架空のDB障害")), self.assertLogs("persona_bot.services.reminder_service", level="ERROR"):
            await button.callback(interaction)
        payload = interaction.edit_original_response.call_args.kwargs
        self.assertIn("一覧を取得できませんでした", payload["content"])
        self.assertNotIn("予定されているリマインダーはありません", payload["content"])
        self.assertIs(payload["view"], hub)
        self.assertFalse(hub.is_finished())
        self.assertTrue(self.db.reminder_is_pending(reminder_id))
        retry = make_interaction()
        await button.callback(retry)
        next_view = retry.edit_original_response.call_args.kwargs["view"]
        self.addCleanup(next_view.stop)
        self.assertIsInstance(next_view, ReminderView)
        self.assertIn("架空の予定", retry.edit_original_response.call_args.kwargs["content"])

    async def test_cancel_db_failure_keeps_select_and_retry_cancels_record(self):
        reminder_id = self.add_reminder()
        view = ReminderView(self.reminders, await self.reminders.list_pending("11"), "11")
        self.addCleanup(view.stop)
        select = next(item for item in view.children if isinstance(item, ReminderCancelSelect))
        select._values = [str(reminder_id)]
        interaction = make_interaction()
        with patch.object(self.db, "reminder_cancel", side_effect=sqlite3.OperationalError("架空のDB障害")), self.assertLogs("persona_bot.services.reminder_service", level="ERROR"):
            await select.callback(interaction)
        payload = interaction.edit_original_response.call_args.kwargs
        self.assertIn("取り消せませんでした", payload["content"])
        self.assertNotIn("既に通知済み", payload["content"])
        self.assertIs(payload["view"], view)
        self.assertFalse(view.is_finished())
        self.assertTrue(self.db.reminder_is_pending(reminder_id))
        retry = make_interaction()
        await select.callback(retry)
        self.assertFalse(self.db.reminder_is_pending(reminder_id))
        self.assertIn("取り消しました", retry.edit_original_response.call_args.kwargs["content"])
        self.assertIsNone(retry.edit_original_response.call_args.kwargs["view"])

    async def test_empty_list_still_displays_no_plans(self):
        _, button = self.make_hub_button()
        interaction = make_interaction()
        await button.callback(interaction)
        payload = interaction.edit_original_response.call_args.kwargs
        self.addCleanup(payload["view"].stop)
        self.assertIn("予定されているリマインダーはありません", payload["content"])

    async def test_cancel_missing_record_and_other_owner_keep_existing_contract(self):
        reminder_id = self.add_reminder()
        records = await self.reminders.list_pending("11")
        self.assertEqual(await self.reminders.list_pending("22"), [])
        self.assertIsNone(await self.reminders.cancel(reminder_id, "22"))
        self.assertTrue(self.db.reminder_is_pending(reminder_id))
        self.assertIsNotNone(await self.reminders.cancel(reminder_id, "11"))
        view = ReminderView(self.reminders, records, "11")
        self.addCleanup(view.stop)
        select = next(item for item in view.children if isinstance(item, ReminderCancelSelect))
        select._values = [str(reminder_id)]
        interaction = make_interaction()
        await select.callback(interaction)
        payload = interaction.edit_original_response.call_args.kwargs
        self.assertIn("既に通知済みか、取り消されています", payload["content"])
        self.assertIsNone(payload["view"])

    async def test_service_distinguishes_storage_errors_from_normal_results(self):
        reminder_id = self.add_reminder()
        for method, operation in (
            ("reminder_list_pending", lambda: self.reminders.list_pending("11")),
            ("reminder_cancel", lambda: self.reminders.cancel(reminder_id, "11")),
        ):
            with self.subTest(method=method):
                error = sqlite3.OperationalError("架空のDB障害")
                with patch.object(self.db, method, side_effect=error), self.assertLogs("persona_bot.services.reminder_service", level="ERROR"):
                    with self.assertRaises(ReminderStorageError) as raised:
                        await operation()
                self.assertIs(raised.exception.__cause__, error)
                self.assertTrue(self.db.reminder_is_pending(reminder_id))

    async def test_failure_after_timeout_uses_private_followup_without_restoring_panel(self):
        reminder_id = self.add_reminder()
        hub, button = self.make_hub_button()
        view = ReminderView(self.reminders, await self.reminders.list_pending("11"), "11")
        self.addCleanup(view.stop)
        select = next(item for item in view.children if isinstance(item, ReminderCancelSelect))
        select._values = [str(reminder_id)]
        for panel, item, method in ((hub, button, "list_pending"), (view, select, "cancel")):
            with self.subTest(method=method):
                async def expire_and_fail(*args):
                    # DB待機中に時間切れとなった状態を、サービス境界で再現する。
                    panel.stop()
                    raise ReminderStorageError("架空の内部エラー詳細")

                interaction = make_interaction()
                with patch.object(self.reminders, method, side_effect=expire_and_fail):
                    await item.callback(interaction)
                interaction.edit_original_response.assert_not_awaited()
                interaction.followup.send.assert_awaited_once()
                notice = interaction.followup.send.call_args
                self.assertTrue(notice.kwargs["ephemeral"])
                self.assertIn("開き直してください", notice.args[0])
                self.assertNotIn("架空の内部エラー詳細", notice.args[0])
                self.assertTrue(self.db.reminder_is_pending(reminder_id))


if __name__ == "__main__":
    unittest.main()
