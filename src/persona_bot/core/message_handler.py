"""起動処理から分離したメッセージ処理。サービスは bot.py から注入する。"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import sys
from typing import TYPE_CHECKING

import discord

from persona_bot.services.affinity_service import extract_affinity_changes
from persona_bot.core.app_state import BotState, GuildSettings, ResponseSettings
from persona_bot.core.background import run_in_thread, spawn
from persona_bot.core.chat_admission import ChatAdmission
from persona_bot.core import message_admission, message_routing, message_response
from persona_bot.core.agent_request import handle_agent_request
from persona_bot.config.constants import (
    AGENT_ROUTER_HISTORY_LIMIT, GEMINI_RESPONSE_TIMEOUT_SECONDS,
    DOCUMENT_QUEUE_FULL_NOTICE, HISTORY_LIMIT, IMAGE_ONLY_QUESTION, MAX_DOCUMENT_SIZE_BYTES,
)
from persona_bot.services.agent_plan import AgentPlan, requests_subagent
from persona_bot.services.content_moderator import screen_bot_response_with_status
from persona_bot.services.violation_notice import record_violation_notice
from persona_bot.utils.discord_helpers import (
    attachment_is_image, clean_message_content, describe_supported_attachments,
    fetch_channel_history_text, format_grounding_sources, mask_grounding_sources, is_supported_document_attachment,
    close_image_attachments, is_connected_voice_chat, is_supported_message_channel,
    load_image_attachments, REPLY_ALLOWED_MENTIONS, send_long_reply,
)
from persona_bot.config.paths import load_persona_template
from persona_bot.services.prompting import (
    build_agent_declined_section, build_full_prompt, build_memory_sections,
)
from persona_bot.audio.voice import play_tts_response
from persona_bot.views.agent_thread import AgentWebhooks, start_agent_progress

if TYPE_CHECKING:
    from persona_bot.services.affinity_service import AffinityService
    from persona_bot.services.agent_service import AgentService
    from persona_bot.services.auto_topic_service import AutoTopicService
    from persona_bot.services.autonomous_service import AutonomousService
    from persona_bot.services.blacklist_service import BlacklistService
    from persona_bot.services.content_moderator import ContentModerator
    from persona_bot.services.document_service import DocumentService
    from persona_bot.services.feedback_service import FeedbackService
    from persona_bot.services.gemini_service import GeminiService
    from persona_bot.services.memory_service import MemoryService
    from persona_bot.services.ng_word_service import NgWordFilter
    from persona_bot.services.reminder_service import ReminderService
    from persona_bot.services.stats_service import StatsService
    from persona_bot.utils.usage_graph import UsageTracker


logger = logging.getLogger(__name__)


@dataclass
class MessageHandler:
    """受信時の関門と応答処理を、明示的に渡されたサービスで実行する。"""

    client: discord.Client
    state: BotState
    auto_topic: AutoTopicService
    autonomous: AutonomousService
    blacklist: BlacklistService
    ng_filter: NgWordFilter
    moderator: ContentModerator
    stats: StatsService
    reminders: ReminderService
    documents: DocumentService
    memory: MemoryService
    affinity: AffinityService
    gemini: GeminiService
    usage: UsageTracker
    feedback: FeedbackService
    agent: AgentService

    def __post_init__(self) -> None:
        self._chat_admission = ChatAdmission()
        # サブエージェントの作業スレッドへ子が投稿する Webhook（チャンネルごとに使い回す。#267）
        self._agent_webhooks = AgentWebhooks()

    async def _screen_response(self, text, sources, *, log_label: str, screen_sources: bool = False):
        return await message_response._screen_response(
            self, text, sources, log_label=log_label, screen_sources=screen_sources,
            runtime=sys.modules[__name__],
        )

    async def notify_violation(self, message: discord.Message, notice: str) -> None:
        """違反を1回記録し、ブロック状況に応じた警告をユーザーに返信する。

        記録の成否はログにも残す。「NGワード検出」のログは記録より前に出るため、
        それだけでは違反が数えられたのか分からない（#173）。
        """
        text, _ = await record_violation_notice(
            self.blacklist, message.author.id, str(message.author), notice,
            blocked_text="以降のメッセージは無視されます。", log=logger,
        )
        if text is not None:
            await self._send_violation_notice(message, text)

    @staticmethod
    async def _send_violation_notice(message: discord.Message, text: str) -> None:
        """違反の保存結果は保持し、通知の送信失敗をイベントへ漏らさない。"""
        try:
            await message.reply(text, allowed_mentions=REPLY_ALLOWED_MENTIONS)
        except discord.DiscordException as error:
            logger.error(f'違反通知: 送信に失敗しました: {type(error).__name__}', exc_info=error)

    async def _reject_ng_input(self, message: discord.Message, question: str, notice: str) -> bool:
        """入力にNGワードがあれば違反として記録し、True を返す（Gemini は呼ばない）。"""
        if not question or not self.ng_filter.contains_ng_word(question):
            return False
        detected = self.ng_filter.find_ng_words(question)
        # 検出した語には非公開の設定や会話が含まれるため、件数だけを記録する。
        logger.info('NGワード検出 (ユーザー入力): %d 件', len(detected))
        await self.notify_violation(message, notice)
        return True

    async def _try_acquire_chat_slot(self, message: discord.Message, guild_id: int | None) -> bool:
        """受付判定と案内枠の記録を、最初の await より前に済ませる。"""
        notice = self._chat_admission.try_acquire(message.author.id, guild_id)
        if notice is None:
            return True
        if self._chat_admission.try_claim_notice(message.author.id):
            try:
                await message.reply(notice, allowed_mentions=discord.AllowedMentions.none())
            except Exception as error:
                logger.error(f'通常会話: 見送り案内の送信に失敗しました: {type(error).__name__}', exc_info=error)
        return False

    async def on_message(self, message: discord.Message) -> None:
        await message_admission.on_message(self, message, runtime=sys.modules[__name__])

    async def _process_accepted_message(
        self, message: discord.Message, question: str, guild_settings: GuildSettings, *,
        accepts_normally: bool, is_autonomous_comment: bool, image_objects: list | None,
    ) -> None:
        await message_routing._process_accepted_message(
            self, message, question, guild_settings, accepts_normally=accepts_normally,
            is_autonomous_comment=is_autonomous_comment, image_objects=image_objects,
            runtime=sys.modules[__name__],
        )

    async def _handle_agent_request(
        self, message: discord.Message, question: str, memory_category: str, plan: AgentPlan,
        response_settings: ResponseSettings, *, image_objects: list | None = None,
    ) -> str | None:
        return await handle_agent_request(
            self, message, question, memory_category, plan, response_settings,
            image_objects=image_objects, start_progress=start_agent_progress,
        )

    async def handle_chat_message(
        self, message: discord.Message, question: str, memory_category: str = "none", *,
        response_settings: ResponseSettings | None = None, delegation_section: str = "",
        delegated_sources: list[dict[str, str]] | None = None, image_objects: list | None = None,
    ) -> str | None:
        """人格役として返信する。読込済み画像は借用し、呼出元が回収する。"""
        return await message_response.handle_chat_message(
            self, message, question, memory_category, response_settings=response_settings,
            delegation_section=delegation_section, delegated_sources=delegated_sources,
            image_objects=image_objects, runtime=sys.modules[__name__],
        )

    def _track_reply_for_feedback(
        self, sent: discord.Message, user_id: str, response_settings: ResponseSettings, generated_model: str,
    ) -> None:
        message_response._track_reply_for_feedback(
            self, sent, user_id, response_settings, generated_model, runtime=sys.modules[__name__],
        )

    async def _remember_reply(self, user_id: str, question: str, response_text: str) -> bool:
        return await message_response._remember_reply(
            self, user_id, question, response_text, runtime=sys.modules[__name__],
        )
