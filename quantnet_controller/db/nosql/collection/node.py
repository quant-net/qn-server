"""
Node
"""

from quantnet_controller.db.nosql.collection import Collection


class Node(Collection):
    def __init__(self):
        self._collection_name = "Node"
