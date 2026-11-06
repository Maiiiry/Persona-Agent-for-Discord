"""メッセージの受付条件・活動観測・入力検査を担当する。

外部境界は呼出元から注入し、サービスの配線と既存の差し替え口を維持する。
"""

from __future__ import annotations

from types import ModuleType

import discord


async def on_message(self, message: discord.Message, *, runtime: ModuleType) -> None:
    if self.client.user is None:
        return
    if message.author == self.client.user or message.author.bot:
        return
    # ブロック中のユーザーは、活動の観測より前に黙って破棄する。後に置くと、無視している
    # はずの発言で自発会話の沈黙タイマーが戻り、自律配信の話したいゲージや無応答での
    # 退出まで左右されてしまう。
    if self.blacklist.is_blocked(message.author.id):
        return
    # 返信も履歴取得もできないチャンネル種別は、NG判定やモデレーション（Gemini 呼び出し）に
    # 進む前にここで打ち切る。後段に置くと、結局返信できない発言のために API を1回
    # 無駄打ちし、違反警告の message.reply() も失敗してしまう。
    channel = message.channel
    if not runtime.is_supported_message_channel(channel):
        return

    is_dm = isinstance(message.channel, runtime.discord.DMChannel)
    # DM はギルドに属さないため guild_id=None として「全DM共有」の設定スロットへ収束させる。
    guild_id = message.guild.id if message.guild is not None else None
    guild_settings = await self.state.get_guild_async(guild_id)
    self.auto_topic.mark_activity(message.channel.id, guild_id)
    # 自律行動の「話したいゲージ」も、ボット宛てでない発言を含めて観測する
    # （このサーバーで会話が行われているかどうかがゲージの材料のため）。
    # 引数の順番は auto_topic 側と同じ (channel_id, guild_id) に揃えてある。
    self.autonomous.mark_activity(message.channel.id, guild_id)

    # 通常のチャット経路が受け付ける条件（応答モードのゲート）。
    # ルーティングでも同じ条件を使うため、判定を1か所にまとめて持ち回す。
    accepts_normally = (
        is_dm
        or guild_settings.current_respond_mode != "mention"
        or self.client.user in message.mentions
    )
    # 配信中のボイス/ステージチャンネル付属のチャットへの書き込みは「コメント」として
    # 扱い、メンションが無くても拾う（傍観者は配信のチャットに気軽に書き込むもので、
    # いちいちメンションを求めるのは配信の体裁に合わないため）。他のテキストチャンネル
    # からの発言はコメントとして認めない（idea.md）ので、判定はチャンネル一致で行う。
    is_autonomous_comment = self.autonomous.is_comment_channel(message.channel.id, guild_id)
    if not accepts_normally and not is_autonomous_comment:
        # 返信しない発言でも、ボットがいま接続しているボイス/ステージの付属チャットだけは
        # ローカルのNGワード判定にかける（#172）。「返信する条件」と「NG判定の対象」を分け、
        # ボットが居合わせている通話のチャットを見守る。AI判定は呼ばない（宛先でない
        # 発言ごとに Gemini を呼ぶとコストが発散する）。他のチャンネルへは広げない。
        if runtime.is_connected_voice_chat(message.guild, message.channel.id):
            await self._reject_ng_input(
                message, runtime.clean_message_content(message, self.client.user), "NGワードが含まれています。",
            )
        return

    question = runtime.clean_message_content(message, self.client.user)
    if not question and not message.attachments:
        return

    if await self._reject_ng_input(message, question, "NGワードが含まれているため、メッセージを処理できません。"):
        return

    await self._process_accepted_message(
        message, question, guild_settings, accepts_normally=accepts_normally,
        is_autonomous_comment=is_autonomous_comment, image_objects=None,
    )
