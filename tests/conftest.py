import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class NullLogger:
    """Logger stub accepting every level and recording nothing.

    Mirrors the Logger facade (info/log/debug/error) so components under test
    can log at any severity without producing output.
    """

    def info(self, msg):
        pass

    log = info

    def debug(self, msg):
        pass

    def error(self, msg):
        pass


@pytest.fixture
def null_logger():
    return NullLogger()
