"""Agent ablations from Milestone 1, Section 6.2, registered so the harness can run them by name."""
from .agent import Agent, AgentConfig
from .baselines.base import register


def _variant(name, desc, **cfg):
    @register(name, needs_llm=True)
    class _V(Agent):
        description = desc

        def __init__(self, env=None, client=None, config=None, **kw):
            super().__init__(env=env, client=client, config=config or AgentConfig(**cfg), **kw)
    _V.__name__ = name
    return _V


_variant("agent_no_skeptic", "Agent without the skeptic pass", use_skeptic=False)
_variant("agent_same_model_skeptic", "Agent, skeptic on the planner model", skeptic_same_model=True)
_variant("agent_no_citation", "Agent without the citation check", use_citation_check=False)
_variant("agent_no_history", "Agent without git_history", use_git_history=False)
