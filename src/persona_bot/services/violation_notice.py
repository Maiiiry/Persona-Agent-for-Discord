"""テキストと音声で共通の違反記録・通知内容を決める。"""

import logging
from typing import Any

from persona_bot.config.constants import BLACKLIST_MAX_VIOLATIONS

logger = logging.getLogger(__name__)


async def record_violation_notice(blacklist: Any, user_id: int, user_name: str, notice: str, *, blocked_text: str, log: logging.Logger = logger) -> tuple[str | None, bool]:
    """保存できない場合は回数を示さず、既存ブロックには重複通知しない。"""
    try:
        count, just_blocked = await blacklist.record_violation(user_id, user_name)
    except Exception as error:
        log.error("違反記録: 保存に失敗したため、今回の違反は回数に数えていません (user_id=<ID>): %s", type(error).__name__, exc_info=error)
        return f"⚠️ {notice}", False
    if just_blocked:
        log.info("違反記録: %d回目の違反でブラックリストに登録しました (user_id=<ID>)", count)
        return f"🚫 違反が{BLACKLIST_MAX_VIOLATIONS}回に達したため、ブラックリストに登録されました。" + blocked_text, True
    if count >= BLACKLIST_MAX_VIOLATIONS:
        log.warning("違反記録: 既にブロック済みのため警告を省略します (user_id=<ID>)")
        return None, False
    log.info("違反記録: %d/%d 回目を記録しました (user_id=<ID>)", count, BLACKLIST_MAX_VIOLATIONS)
    remaining = BLACKLIST_MAX_VIOLATIONS - count
    return f"⚠️ {notice}（あと{remaining}回で応答を停止します）", False
