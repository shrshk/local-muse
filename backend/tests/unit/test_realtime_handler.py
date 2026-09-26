import jwt

from muse.modules.realtime.realtime_handler import RealtimeHandler
from muse.shared.settings import Settings


def test_connection_token_is_signed_and_carries_the_user():
    settings = Settings(centrifugo_token_secret="s" * 32, centrifugo_token_ttl_seconds=600)
    out = RealtimeHandler(settings).connection_token("owner")

    claims = jwt.decode(out.token, "s" * 32, algorithms=["HS256"])
    assert claims["sub"] == "owner"
    assert claims["exp"] - claims["iat"] == 600
    assert out.expires_in == 600
