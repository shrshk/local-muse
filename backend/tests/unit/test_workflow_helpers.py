import uuid

import jwt
from pydantic_ai.messages import ModelRequest, ModelResponse

from muse.modules.realtime.realtime_handler import RealtimeHandler
from muse.shared.settings import Settings
from muse.worker.__main__ import model_activities
from muse.workflows.conversation import to_model_history
from muse.workflows.schema import HistoryItem


def test_history_maps_roles_to_model_messages():
    history = to_model_history(
        [HistoryItem(role="user", content="hi"), HistoryItem(role="assistant", content="hello")]
    )
    assert isinstance(history[0], ModelRequest)
    assert isinstance(history[1], ModelResponse)


def test_subscription_token_names_the_channel():
    secret = "s" * 32
    handler = RealtimeHandler(Settings(centrifugo_token_secret=secret))
    channel = f"conversation:{uuid.uuid4()}"
    token = handler.subscription_token("user-1", channel).token
    claims = jwt.decode(token, secret, algorithms=["HS256"])
    assert claims["channel"] == channel
    assert claims["sub"] == "user-1"


def test_model_worker_registers_only_model_activities():
    names = [getattr(a, "__temporal_activity_definition").name for a in model_activities()]
    assert names
    assert all("__model_" in n for n in names)
    assert not any("toolset" in n or "event_stream" in n for n in names)
