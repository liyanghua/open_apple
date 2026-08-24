"""Unit tests for lib.voice_timeline_fit (R1 ladder)."""

from __future__ import annotations

import pytest

from lib.voice_timeline_fit import (
    SPEECH_RATE_LADDER,
    decide_adaptation,
    fits_slot,
    next_speech_rate,
)


def test_fits_slot_with_tolerance():
    assert fits_slot(3.0, 3.0) is True
    assert fits_slot(3.0, 3.01) is True  # 容忍 0.02s
    assert fits_slot(3.0, 3.03) is False


def test_next_speech_rate_ladder():
    assert next_speech_rate(0) == 10
    assert next_speech_rate(10) == 20
    assert next_speech_rate(20) == 50
    assert next_speech_rate(50) is None  # 顶档耗尽


def test_decide_adaptation_order():
    # 落入槽位 → ok
    assert decide_adaptation(3.0, 2.9, 0)["action"] == "ok"
    # 超槽位 → 先提语速（retry），阶梯依次 +10/+20/+50
    assert decide_adaptation(3.0, 3.5, 0) == {"action": "retry", "speech_rate": 10, "fits": False}
    assert decide_adaptation(3.0, 3.5, 10)["speech_rate"] == 20
    assert decide_adaptation(3.0, 3.5, 20)["speech_rate"] == 50
    # 语速顶档仍超槽位 → rewrite（改写文案）
    assert decide_adaptation(3.0, 3.5, 50)["action"] == "rewrite"


def test_ladder_is_ascending():
    assert list(SPEECH_RATE_LADDER) == [0, 10, 20, 50]
    assert SPEECH_RATE_LADDER == tuple(sorted(SPEECH_RATE_LADDER))


def test_next_speech_rate_unknown_rate_fails_closed():
    with pytest.raises(ValueError):
        next_speech_rate(99)  # 未知档位：报错，不静默回起点


def test_decide_adaptation_escalates_after_rewrite():
    # 语速阶梯耗尽 + 已改写（rewrite_round=1）→ escalate
    assert decide_adaptation(3.0, 3.5, 50, rewrite_round=1)["action"] == "escalate"
    # 语速阶梯耗尽 + 未改写（rewrite_round=0）→ rewrite
    assert decide_adaptation(3.0, 3.5, 50, rewrite_round=0)["action"] == "rewrite"
