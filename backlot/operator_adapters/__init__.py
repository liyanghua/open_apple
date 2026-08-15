"""Explicit registry for the six operator-editable stages."""

from .assets import AssetsAdapter
from .proposal import ProposalAdapter
from .research import ResearchAdapter
from .sample import SampleAdapter
from .scene_plan import ScenePlanAdapter
from .script import ScriptAdapter


_ADAPTERS = {
    adapter.stage: adapter
    for adapter in (
        ResearchAdapter(),
        ProposalAdapter(),
        ScriptAdapter(),
        ScenePlanAdapter(),
        AssetsAdapter(),
        SampleAdapter(),
    )
}


def get_adapter(stage: str):
    return _ADAPTERS[stage]


__all__ = ["get_adapter"]
