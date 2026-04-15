import time
import logging
import importlib
import sys

from bson.objectid import ObjectId
from quantnet_controller.common.config import Config
from quantnet_controller.common.utils import get_uri_path


class DBLayer(object):
    """
    A simple wrapper for Mongo collections.

    Uncapped collections in Mongo must have a uniqe '_id'
    field, so this layer will generate one for each insert based on the
    network resource id and the revision number (timestamp).
    """

    def __init__(self, client, collection_name, capped=False, Id="id", timestamp="ts", *, history=False):
        self.log = logging.getLogger(__name__)
        self.Id = Id
        self.timestamp = timestamp
        self.history, self.capped = history, capped
        self._collection_name = collection_name
        self._client = client

    @property
    def collection(self):
        """Returns a reference to the default mongodb collection."""
        return self._client[self._collection_name]

    @property
    def manifest(self):
        """Returns a reference to the manifest collection"""
        return self._client["manifests"]

    def find_one(self, query={}, **kwargs):
        self.log.debug(f"Find one for collection: [{self._collection_name}]")
        fields = kwargs.pop("fields", {})
        fields["_id"] = 0
        result = self.collection.find_one(query, projection=fields, **kwargs)
        return result

    def count(self, query={}, **kwargs):
        skip = kwargs.get("skip", 0)
        if "limit" in kwargs:
            return self.collection.count_documents(query, skip=skip, limit=kwargs["limit"])
        return self.collection.count_documents(query, skip=skip)

    def find(self, query={}, **kwargs):
        """Finds one or more elements in the collection."""
        self.log.debug(f"Find for collection: [{self._collection_name}")
        fields = kwargs.pop("fields", {})
        fields["_id"] = 0
        return self.collection.find(query, fields, **kwargs)

    def _insert_id(self, data):
        if "_id" not in data and not self.capped:
            res_id = data.get(self.Id, str(ObjectId()))
            timestamp = data.get(self.timestamp, int(time.time() * 1e6))
            data["_id"] = f"{res_id}:{timestamp}" if self.history else res_id

    def insert(self, data, summarize=True, **kwargs):
        """Inserts data to the collection."""
        self.log.debug(f"Insert for collection: [{self._collection_name}")
        data = [data] if not isinstance(data, list) else data
        if not self.capped:
            for item in data:
                self._insert_id(item)

        if self.history:
            results = self.collection.insert_many(data, **kwargs)
        else:
            results = []
            for item in data:
                rid = item.get(self.Id, str(ObjectId()))
                results.append(self.collection.replace_one({self.Id: rid}, item, upsert=True))
        return results

    def upsert(self, query, data):
        return self.collection.replace_one(query, data, upsert=True)

    def update(self, query, data, replace=False, multi=True, **kwargs):
        """Updates data found by query in the collection."""
        self.log.debug(f"Update for Collection: [{self._collection_name}")
        if not replace:
            data = {"$set": data}
        if multi:
            results = self.collection.update_many(query, data)
        else:
            results = self.collection.find_one_and_update(query, data, upsert=False, **kwargs)
            for r in results:
                if isinstance(r, dict) and not r.get("updatedExisting", True):
                    raise (LookupError("Resource ID does not exist"))
        return results

    def remove(self, query, callback=None, **kwargs):
        self.log.debug(f"Remove for collection: [{self._collection_name}]")
        results = self.collection.delete_many(query)
        return results

    def drop(self, **kwargs):
        self.collection.drop()

    def drop_database(self, **kwargs):
        self._client.db.command("dropDatabase")


class DBLoader:
    def __init__(self, engine="pymongo.MongoClient", **kwargs):
        self.log = logging.getLogger(__name__)
        self._engine = engine
        self._softstart = kwargs.get("softstart")
        self._pollrate = kwargs.get("pollrate")
        self._host = kwargs.get("host")
        self._port = kwargs.get("port")
        self._dbname = kwargs.get("dbname", "quantnet")
        self._db = self._init()

    @property
    def db(self):
        return self._db

    def _init(self):
        modpath = self._engine.split(".")
        try:
            Client = getattr(importlib.import_module(".".join(modpath[:-1])), modpath[-1])
        except ImportError:
            self.log.error("Failed to import database client module")
            exit(-1)
        while True:
            try:
                url = Config().get('database', 'default',
                                 default="mongodb://localhost",
                                 check_config_table=False)
                path = get_uri_path(url)
                self._dbname = path if path else self._dbname
                self._conn = Client(url)
                break
            except Exception as exp:
                self.log.error(f"Failed to connect to the client service - {exp}")
                if not self._softstart:
                    sys.exit()
                time.sleep(int(self._pollrate))
        self._db = self._conn[self._dbname]
        return self._db

    def drop_database(self, **kwargs):
        self._conn.drop_database(self._dbname)

    def get_db_layer(self, collection_name, id_field_name):
        if not collection_name:
            return None
        db_layer = DBLayer(self.db, collection_name, False, id_field_name)
        return db_layer
