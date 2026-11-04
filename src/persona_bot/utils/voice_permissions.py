"""ボイス・ステージの用途別の実効権限を確認する。"""

from typing import Any


def missing_voice_permissions(
    channel: Any, member: Any, *, speak: bool = True, text: bool = False,
    stage_moderation: bool = False,
) -> list[str]:
    """接続前に必要な権限を、表示順を保って返す。"""
    return missing_voice_permissions_for(
        channel.permissions_for(member), speak=speak, text=text, stage_moderation=stage_moderation,
    )


def missing_voice_permissions_for(
    permissions: Any, *, speak: bool = True, text: bool = False, stage_moderation: bool = False,
) -> list[str]:
    """取得済みの権限から不足項目を返す。"""
    checks = [("チャンネルを見る", permissions.view_channel), ("接続", permissions.connect)]
    if speak:
        checks.append(("発言", permissions.speak))
    if text:
        checks.append(("メッセージを送信", permissions.send_messages))
    if stage_moderation:
        checks.append(("メンバーをミュート", permissions.mute_members))
    return [name for name, allowed in checks if not allowed]
