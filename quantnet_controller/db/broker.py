"""
Broker
"""

import os
import abc
from enum import Enum
from typing import TYPE_CHECKING
from sqlalchemy.engine import url  # , make_url
from urllib.parse import urlparse
from functools import wraps
from quantnet_controller.common.config import Config
from quantnet_controller.utils.util import import_classes_from_package
from quantnet_controller.db.nosql.collection import Collection
from quantnet_controller.db.sqla.model import Blob


if TYPE_CHECKING:
    from typing import Callable, Optional, ParamSpec, TypeVar
    P = ParamSpec("P")
    R = TypeVar("R")

DATABASE_SECTION = 'database'
__BROKER = None


class BrokerType(Enum):
    SQLA = 'sqla'
    MONGO = 'mongo'


def is_dialect_supported(database_url: str):
    try:
        parsed_url = url.make_url(database_url)
        return parsed_url.get_dialect().name is not None
    except Exception:
        return False


def check_database_type(database_url: str):
    if is_dialect_supported(database_url):
        return BrokerType.SQLA
    elif urlparse(database_url).scheme == "mongodb":
        return BrokerType.MONGO
    else:
        raise Exception(f'{database_url} is not supported')


class Broker(object, metaclass=abc.ABCMeta):
    def _get_hndl(self, model):
        return self.classes[model]() if self.classes.get(model) else self.default(model)

    def add(self, model, data, **kwargs):
        return self._get_hndl(model).add(data, **kwargs)

    def get(self, model, id, **kwargs):
        return self._get_hndl(model).get(id, **kwargs)

    def find(self, model, **kwargs):
        return self._get_hndl(model).find(**kwargs)

    def update(self, model, id, key, value, **kwargs):
        return self._get_hndl(model).update(id, key, value, **kwargs)

    def upsert(self, model, id, *args, **kwargs):
        return self._get_hndl(model).upsert(id, *args, **kwargs)

    def delete(self, model, id, **kwargs):
        return self._get_hndl(model).delete(id, **kwargs)

    def exist(self, model, id, **kwargs):
        return self._get_hndl(model).exist(id, **kwargs)

    def drop(self, model, **kwargs):
        return self._get_hndl(model).drop(**kwargs)

    def drop_database(self, model, **kwargs):
        return self._get_hndl(model).drop_database(**kwargs)


class SqlaBroker(Broker):
    def __init__(self, **kwargs):
        current_file_directory = os.path.dirname(os.path.abspath(__file__))
        self.classes = import_classes_from_package(f"{current_file_directory}/sqla/model")
        self.default = Blob


class MongoBroker(Broker):
    def __init__(self, **kwargs):
        current_file_directory = os.path.dirname(os.path.abspath(__file__))
        self.classes = import_classes_from_package(f"{current_file_directory}/nosql/collection")
        self.default = Collection


def broker(func: "Callable[P, R]"):
    """ Decorate a function that set the broker variable
    """
    @wraps(func)
    def wrapper(*args: "P.args", broker: "Optional[Broker]" = None, **kwargs):
        global __BROKER
        if __BROKER is None:
            url = Config().get(DATABASE_SECTION, 'default',
                             default="mongodb://localhost",
                             check_config_table=False)
            broker_type = check_database_type(url)
            if broker_type == BrokerType.SQLA:
                broker = SqlaBroker()
            elif broker_type == BrokerType.MONGO:
                broker = MongoBroker()
            else:
                raise Exception(f"{url} not implemented")
            __BROKER = broker
        else:
            broker = __BROKER

        return func(*args, broker=broker, **kwargs)

    return wrapper
