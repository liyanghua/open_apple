"""Explicit registry for the operator-editable stages."""

from .assets import AssetsAdapter
from .delivery_review import DeliveryReviewAdapter
from .edit import EditAdapter
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
        DeliveryReviewAdapter(),
        EditAdapter(),
        SampleAdapter(),
    )
}


def get_adapter(stage: str):
    return _ADAPTERS[stage]


__all__ = ["get_adapter"]
