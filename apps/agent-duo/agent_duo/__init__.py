"""Two agents that talk to each other: Scout reads public content via agent-reach, Critic checks and answers."""

from .orchestrator import Orchestrator, OrchestratorError, Result, Settings

__all__ = ["Orchestrator", "OrchestratorError", "Result", "Settings"]
