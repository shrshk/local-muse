import httpx
import pytest

from muse.models.factory import ProviderConfigError, build_provider
from muse.shared.settings import Settings


def test_offline_mode_builds_the_local_provider():
    provider = build_provider(Settings(local_muse_mode="offline"), httpx.AsyncClient())
    assert provider.is_local


@pytest.mark.parametrize("mode", ["hybrid", "cloud"])
def test_non_offline_modes_are_refused_in_v1(mode: str):
    with pytest.raises(ProviderConfigError):
        build_provider(Settings(local_muse_mode=mode), httpx.AsyncClient())  # type: ignore[arg-type]
