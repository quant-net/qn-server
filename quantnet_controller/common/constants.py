import os
import uuid
import quantnet_controller
from enum import Enum
from datetime import timedelta


class Constants:
    INSTANCE_UUID = uuid.uuid4()
    DEFAULT_TEST_DB_NAME = "quantnet_test"
    DEFAULT_TEST_DB_URI = f"mongodb://localhost:27017/{DEFAULT_TEST_DB_NAME}"
    SLOTSIZE = timedelta(milliseconds=100)
    MAX_TIMESLOTS = 500
    NODE_HEARTBEAT_TIMEOUT = 60  # seconds
    PLUGIN_PATH = os.path.join(os.path.dirname(quantnet_controller.__file__), "plugins")
    DEFAULT_EXP_DEFS = os.path.join(os.path.dirname(quantnet_controller.__file__),
                                    "plugins/protocols/agentExperiment/exp_defs.py")
    DEFAULT_SCHEDULER = "BatchScheduler"
    DEFAULT_ROUTER = "PathFinder"
    DEFAULT_MONITOR = "Monitor"


class CalibrationType(int, Enum):
    def __new__(cls, value, label):
        obj = int.__new__(cls, value)
        obj._value_ = value
        obj.label = label
        return obj

    LINK_STAB = (1, "Link Stabilization")
    BSM_POL = (2, "BSM Polarization")
