# pytest Configuration and Fixtures
# conftest.py is automatically discovered by pytest
# Provides global fixtures and configuration for all tests

import sys
from pathlib import Path

# Add test stubs and project root to path so imports work
tests_dir = Path(__file__).resolve().parent
stubs_dir = tests_dir / 'stubs'
sys.path.insert(0, str(stubs_dir))
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



# Optional: Configuration for pytest
def pytest_configure(config):
    """Configure pytest behavior."""
    # Can add custom markers, disable warnings, etc.
    pass
