"""話者の予約と文字起こしの帰属を、音声接続なしで検証する。"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from persona_bot.config.constants import LIVE_SPEAKER_REQUEST_TTL_SECONDS
from persona_bot.services.voice_conversation import _SpeakerState, _TranscriptState, _Utterance


class SpeakerStateTests(unittest.TestCase):
    def test_reservation_expires_and_duplicate_requests_do_not_change_order(self):
        state = _SpeakerState()
        state.request_floor(1, 0.0)
        state.request_floor(1, 0.5)
        state.request_floor(2, 1.0)
        self.assertFalse(state.floor_available(2, 1.0))
        self.assertTrue(state.floor_available(2, LIVE_SPEAKER_REQUEST_TTL_SECONDS + 0.5))

    def test_active_speaker_frames_are_forwarded_and_others_reserved(self):
        state = _SpeakerState(active_user=1, speaking=True)
        frame = (20000).to_bytes(2, "little", signed=True) * 320
        action, _ = state.receive(1, frame, 1.0, bot_speaking=lambda: False)
        self.assertEqual(action, "send")
        for index in range(20):
            state.receive(2, frame, 1.0 + index * 0.02, bot_speaking=lambda: False)
        self.assertEqual([user for user, _ in state.reservations], [2])


class TranscriptStateTests(unittest.TestCase):
    def test_overlapping_transcripts_do_not_change_the_previous_owner(self):
        state = _TranscriptState()
        first, second, third = (_Utterance(index, index, 0.0) for index in (1, 2, 3))
        state.assign(first, 1.0)
        state.assign(second, 2.0)
        state.assign(third, 3.0)
        self.assertIsNone(state.owner)
        self.assertIs(state.blocked, first)
        self.assertTrue(second.transcript_incomplete)
        state.close(first)
        self.assertIs(state.owner, third)
        state.reset()
        self.assertTrue(third.transcript_closed)
        self.assertIsNone(state.owner)
