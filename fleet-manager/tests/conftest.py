import pytest

from fleetmanager import esc


@pytest.fixture(autouse=True)
def fast_esc_timings(monkeypatch):
    """The real boot and retry delays (seconds) are not needed against the simulator."""
    monkeypatch.setattr(esc, "ESC_BOOT_DELAY", 0)
    monkeypatch.setattr(esc, "ESC_RETRY_DELAY", 0)
