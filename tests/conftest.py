"""Bật nạp tích hợp tuỳ chỉnh trong HA thử."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
