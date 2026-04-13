"""
Calibration
"""

from quantnet_controller.db.nosql.collection import Collection


class Calibration(Collection):
    def __init__(self):
        self._collection_name = "Calibration"
