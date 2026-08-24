"""voice-timeline-fit：TTS 实测时长驱动的口播时间轴适配（R1 固化）。

固化自 `skills/meta/voice-timeline-fit.md`。豆包 TTS 每段实测时长经常超出剧本
段落槽位，手工调语速既慢又易错。此模块把「先测量、后适配」的决策阶梯固化为纯
函数：不碰 provider、不写盘，只根据 `slot_s` 与实测 `audio_s` 返回下一步动作，
供样片 stage 服务与批量脚本复用同一套调参。
"""
from __future__ import annotations

from typing import Any

# 豆包 seed-tts-2.0 speech_rate 阶梯：0 = 1.0x，+10 = 1.1x，+20 = 1.2x，+50 = 1.5x。
# 决策顺序见 skills/meta/voice-timeline-fit.md：逐段提语速 → 改写文案 → 升格结构。
SPEECH_RATE_LADDER = (0, 10, 20, 50)

# 实测时长允许略超槽位的容忍量（秒）。超过才触发适配，避免浮点误差误判。
DEFAULT_TOLERANCE_S = 0.02


def fits_slot(slot_seconds: float, audio_seconds: float, *, tolerance: float = DEFAULT_TOLERANCE_S) -> bool:
    """实测音频是否落入段落槽位（含容忍量）。"""
    return float(audio_seconds) <= float(slot_seconds) + float(tolerance)


def next_speech_rate(current_rate: int) -> int | None:
    """返回阶梯中下一档 speech_rate；已到顶档（+50）则返回 None。

    未知档位 fail-closed：抛 ValueError，绝不静默从阶梯起点重试（那会造成
    无效的重复生成）。
    """
    if current_rate not in SPEECH_RATE_LADDER:
        raise ValueError(f"unknown speech_rate {current_rate!r}; expected one of {SPEECH_RATE_LADDER}")
    idx = SPEECH_RATE_LADDER.index(int(current_rate))
    nxt = idx + 1
    return SPEECH_RATE_LADDER[nxt] if nxt < len(SPEECH_RATE_LADDER) else None


def decide_adaptation(
    slot_seconds: float,
    audio_seconds: float,
    current_rate: int,
    *,
    rewrite_round: int = 0,
    tolerance: float = DEFAULT_TOLERANCE_S,
) -> dict[str, Any]:
    """对「实测超槽位」的段落返回下一步动作（纯函数，不做任何生成）。

    返回 ``{action, speech_rate, fits}``：
    - ``ok``      实测已落入槽位（含容忍）；
    - ``retry``   仍有语速档可提，用返回的 ``speech_rate`` 重新生成并重测；
    - ``rewrite`` 语速阶梯耗尽且尚未改写过（rewrite_round==0），需改写文案；
    - ``escalate`` 已改写（rewrite_round>=1）仍放不下，升格为结构问题。
    """
    if fits_slot(slot_seconds, audio_seconds, tolerance=tolerance):
        return {"action": "ok", "speech_rate": int(current_rate), "fits": True}
    nxt = next_speech_rate(int(current_rate))
    if nxt is not None:
        return {"action": "retry", "speech_rate": nxt, "fits": False}
    if int(rewrite_round) <= 0:
        return {"action": "rewrite", "speech_rate": int(current_rate), "fits": False}
    return {"action": "escalate", "speech_rate": int(current_rate), "fits": False}
