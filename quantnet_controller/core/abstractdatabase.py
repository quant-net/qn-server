from quantnet_controller.db.broker import broker as db_broker, Broker


class DBmodel():
    Node = "Node"
    Request = "Request"
    Monitor = "Monitor"
    Calibration = "Calibration"
    PingPong = "PingPong"
    Blob = "Blob"


class AbstractDatabase():
    """
    AbstractDatabase class
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AbstractDatabase, cls).__new__(cls)
        return cls._instance

    class DBModel():
        def __init__(self, db, model):
            self._db = db
            self._model = model

        def add(self, data, **kwargs) -> dict:
            return self._db.add(self._model, data, **kwargs)

        def get(self, id, **kwargs) -> dict | None:
            return self._db.get(self._model, id, **kwargs)

        def find(self, **kwargs) -> list:
            return self._db.find(self._model, **kwargs)

        def update(self, id, key, value, **kwargs) -> bool:
            return self._db.update(self._model, id, key, value, **kwargs)

        def upsert(self, id, *args, **kwargs) -> bool:
            return self._db.upsert(self._model, id, *args, **kwargs)

        def delete(self, id, **kwargs) -> int:
            return self._db.delete(self._model, id, **kwargs)

        def exist(self, id, **kwargs) -> bool:
            return self._db.exist(self._model, id, **kwargs)

        def drop(self, **kwargs) -> None:
            return self._db.drop(self._model, **kwargs)

    def handler(self, model=DBmodel.Blob):
        """
        return the table handler
        """
        h = AbstractDatabase.DBModel(self, model)
        return h

    @staticmethod
    @db_broker
    def get_broker(broker: Broker) -> Broker:
        """ Get the broker instance """
        return broker

    @staticmethod
    @db_broker
    def drop_database(broker: Broker, **kwargs):
        """ Drop the entire DB """
        return broker.drop_database(model=None, **kwargs)

    @staticmethod
    @db_broker
    def drop(model, broker: Broker, **kwargs):
        """ Drop the current model (collection) """
        return broker.drop(model, **kwargs)

    @staticmethod
    @db_broker
    def add(model, data, broker: Broker, **kwargs):
        """ Insert data into the database table or collection.

        :param model: table or collection.
        :type model: enum DBModel
        :param data: data to insert
        :type data: dict
        :return: the inserted data with id
        :rtype: tuple (id, data) or tuple list [(id, data)...]

        **Example:**

        .. code-block:: python

            add(DBmodel.Blob, {"name":"alice", "remote":"bob"})

        """
        return broker.add(model, data, **kwargs)

    @staticmethod
    @db_broker
    def get(model, id, broker: Broker, **kwargs):
        """ Get the records from the database table or collection. It allows filtering based on "id"

        :param model: table or collection
        :type model: enum DBModel
        :param id: id of data
        :type id: either index string or filter dict
        :return: data
        :rtype: dict or None

        **Example:**

        .. code-block:: python

            get(DBmodel.Blob, "1234")
            get(DBmodel.Blob, {"name":"alice"})

        """
        return broker.get(model, id, **kwargs)

    @staticmethod
    @db_broker
    def find(model, broker: Broker, **kwargs) -> list:
        """ Find all records of the database table or collection.

        :param model: table or collection
        :type mdoel: enum DBModel
        :return: data or list of data
        :rtype: list of dicts or empty list

        **Example:**

        .. code-block:: python

            find(DBmodel.Blob)

        """
        return broker.find(model, **kwargs)

    @staticmethod
    @db_broker
    def update(model, id, key, value, broker: Broker, **kwargs):
        """ Update with {key:value} the database table or collection based on the id.
            If nothing matching the id, nothing happens.

        :param model: table or collection
        :type model: enum DBModel
        :param id: id of data
        :type id: index str or filter dict
        :param key: data key
        :type key: string
        :param value: data value
        :type value: string

        **Example:**

        .. code-block:: python

            update(DBmodel.Blob, "1234", key = "name", value="alice")

        """
        return broker.update(model, id, key, value, **kwargs)

    @staticmethod
    @db_broker
    def upsert(model, id, *args, broker: Broker, **kwargs):
        """ It updates a record if exists or adds a new record if it does not.
        Unmodified fields retain their original values.

        param model: table or collection
        type model: enum DBModel
        param id: id of data
        type id: index str or filter dict
        param args: new data
        type args: dicts

        **Example:**

        .. code-block:: python

            upsert(DBmodel.Blob, "1234", {"name":"alice"}, {remote":"bob})
            upsert(DBmodel.Blob, {"name":"alice"}, {"name":"charlie"}, {remote":"bob})

        """
        return broker.upsert(model, id, *args, **kwargs)

    @staticmethod
    @db_broker
    def delete(model, id, broker: Broker, **kwargs):
        """ Remove records from the database table or collection, with the option to filter by "id".

        :param model: table or collection
        :type model: enum DBModel
        :param id: id of data
        :type id: either index string or filter dict
        :return: number of items deleted
        :rtype: int

        **Example:**

        .. code-block:: python

            delete(DBmodel.Blob, "1234")
            delete(DBmodel.Blob, {"name":"alice", "remote": "bob"})

        """
        return broker.delete(model, id, **kwargs)

    @staticmethod
    @db_broker
    def exist(model, id, broker: Broker, **kwargs):
        """ Verify the existence of records in the database, with the option to filter by "id"

        :param model: table or collection
        :type model: enum DBModel
        :param id: id of data
        :type id: either index string or filter dict
        :return: result
        :rtype: boolean

        **Example:**

        .. code-block:: python

            exist(DBmodel.Blob, "1234")

        """
        return broker.exist(model, id, **kwargs)
