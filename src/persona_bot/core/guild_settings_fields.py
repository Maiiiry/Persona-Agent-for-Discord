"""サーバー設定の保存列と実行時属性の対応。"""

from persona_bot.config.constants import DEFAULT_AUTO_TOPIC_INTERVAL_HOURS, DEFAULT_MODEL_NAME, DEFAULT_RESPOND_MODE
from persona_bot.config.personas import FOLLOW_DEFAULT_PERSONA

# 型は DB 保存時の変換方法。チャンネルの未指定は DB では 0。
GUILD_SETTINGS_FIELDS = (
    ("prompt_file", "current_prompt_file", "text", FOLLOW_DEFAULT_PERSONA),
    ("model_name", "current_model_name", "text", DEFAULT_MODEL_NAME),
    ("respond_mode", "current_respond_mode", "text", DEFAULT_RESPOND_MODE),
    ("grounding_enabled", "grounding_enabled", "bool", True),
    ("auto_topic_enabled", "auto_topic_enabled", "bool", False),
    ("auto_topic_interval_hours", "auto_topic_interval_hours", "int", DEFAULT_AUTO_TOPIC_INTERVAL_HOURS),
    ("autonomous_enabled", "autonomous_enabled", "bool", False),
    ("autonomous_stage_channel_id", "autonomous_stage_channel_id", "channel", None),
    ("autonomous_voice_channel_id", "autonomous_voice_channel_id", "channel", None),
)
GUILD_SETTINGS_DEFAULTS = {name: default for name, _, _, default in GUILD_SETTINGS_FIELDS}
