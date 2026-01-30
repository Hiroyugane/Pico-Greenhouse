# pytest Configuration and Fixtures
# conftest.py is automatically discovered by pytest
# Provides global fixtures and configuration for all tests

import sys
from pathlib import Path

# Add project root to path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Mock MicroPython modules before any imports
from unittest.mock import MagicMock

# Create mock for 'machine' module
sys.modules['machine'] = MagicMock()

# Create mock for 'dht' module
sys.modules['dht'] = MagicMock()

# Create mock for 'uasyncio' module (use standard asyncio)
import asyncio
sys.modules['uasyncio'] = asyncio

# Create mock for 'lib.ds3231' module
sys.modules['lib'] = MagicMock()
sys.modules['lib.ds3231'] = MagicMock()

# Create mock for 'lib.sdcard' module
sys.modules['lib.sdcard'] = MagicMock()


# Optional: Configuration for pytest
def pytest_configure(config):
    """Configure pytest behavior."""
    # Can add custom markers, disable warnings, etc.
    pass
