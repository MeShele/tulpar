"""
Pytest configuration for Tulpar Express tests

Configures:
- pytest-asyncio for async tests
- Common fixtures
"""
import pytest


# Configure pytest-asyncio to auto-detect async tests
pytest_plugins = ('pytest_asyncio',)


def pytest_configure(config):
    """Configure pytest markers"""
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )
