from functools import wraps
from quantnet_controller.db.nosql.db import DBLoader

DATABASE_SECTION = 'database'

_DATABASE = None
_COLLECTION_CONFIG = None


def init_collection_config(config):
    global _COLLECTION_CONFIG
    _COLLECTION_CONFIG = config


class Collection:
    # Reserve '_id' as unique key in collections
    # This means if the user include '_id' as a data field,
    # add() will upsert that record preserving uniqueness.
    # Otherwise, a new internal '_id' will be generated but
    # will not be exposed to user.
    _keyname = "_id"

    def __init__(self, model="default"):
        self._collection_name = model if model else "default"

    def layer(func):
        """ Decorate a function that set the layer variable
        """
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            key = Collection._keyname
            global _DATABASE
            if _DATABASE is None:
                _DATABASE = DBLoader(config=_COLLECTION_CONFIG)
            layer = _DATABASE.get_db_layer(self._collection_name, key)
            return func(self, *args, **kwargs, layer=layer)
        return wrapper

    @layer
    def add(self, data, layer=None, **kwargs) -> str:
        if not isinstance(data, dict):
            raise Exception(f"Type error: {data} is not dict")
        try:
            docs = layer.insert(data)
            if len(docs) == 1 and docs[0].upserted_id:
                return data
            else:
                return None
        except Exception:
            raise

    @layer
    def find(self, layer=None, **kwargs):
        try:
            q = kwargs.pop("filter", {})
            return [doc for doc in layer.find(q, **kwargs)]
        except Exception:
            raise

    @layer
    def get(self, id, layer=None, **kwargs):
        """ Get the documents from the collection. It allows filtering based on "id"

        parameters:
        -----------
        id: str or dict
            either id string or filter dict

        """
        if isinstance(id, dict):
            filter = id
        elif isinstance(id, str):
            filter = {self._keyname: id}
        else:
            raise Exception(f"{id} must be either dict or str")
        try:
            result = layer.find_one(filter)
            return result
        except Exception:
            raise

    @layer
    def update(self, id, key, value, layer=None):
        filter = {self._keyname: id} if not isinstance(id, dict) else id
        try:
            object = layer.update(filter, {key: value})
            return True if object.modified_count else False
        except Exception:
            raise

    @layer
    def upsert(self, id, *args, layer=None, **kwargs):
        def combine(*args):
            combined_dict = {}
            for d in args:
                combined_dict.update(d)
            return combined_dict

        try:
            data = combine(*args) if args else {}
            if not data:
                return

            filter = {self._keyname: id} if not isinstance(id, dict) else id

            if layer.find_one(filter):
                ret = layer.update(filter, data)
                return True if ret.modified_count else False
            else:
                return self.add(data)
        except Exception:
            raise

    @layer
    def delete(self, id, layer=None):

        filter = {self._keyname: id} if not isinstance(id, dict) else id
        try:
            object = layer.remove(filter)
        except Exception:
            raise
        return object.deleted_count

    @layer
    def exist(self, id, layer=None, **kwargs):
        filter = {self._keyname: id} if not isinstance(id, dict) else id
        return True if layer.find_one(filter) else False

    @layer
    def drop(self, layer=None, **kwargs):
        return layer.drop(**kwargs)

    @layer
    def drop_database(self, layer=None, **kwargs):
        global _DATABASE
        _DATABASE.drop_database(**kwargs)
