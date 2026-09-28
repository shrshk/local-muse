"""Replay recorded histories against the current workflow code.

A workflow change that alters the command sequence of already-recorded runs fails here instead of
stranding open conversations in production. Fixtures come from `make history`.
"""

import gzip
import json
import pathlib

import pytest
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer

from muse.workflows.conversation import ConversationWorkflow
from muse.workflows.goals import GoalRunWorkflow, GoalWorkflow
from muse.workflows.topic import TopicWorkflow

HISTORIES = sorted((pathlib.Path(__file__).parent / "histories").glob("*.json.gz"))


def load(path: pathlib.Path) -> WorkflowHistory:
    with gzip.open(path, "rt") as f:
        doc = json.load(f)
    return WorkflowHistory.from_json(doc["workflow_id"], doc["history"])


def test_fixtures_exist():
    assert len(HISTORIES) >= 10


@pytest.mark.parametrize("path", HISTORIES, ids=lambda p: p.name.removesuffix(".json.gz"))
async def test_history_replays(path: pathlib.Path):
    replayer = Replayer(
        workflows=[ConversationWorkflow, TopicWorkflow, GoalWorkflow, GoalRunWorkflow],
        plugins=[PydanticAIPlugin()],
    )
    await replayer.replay_workflow(load(path))
