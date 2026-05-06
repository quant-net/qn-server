"""Unit test package for quantnet_controller."""

import os
import logging
import json
import quantnet_mq.schema
from quantnet_controller.common.constants import Constants
from quantnet_controller.common.config import global_config
from quantnet_controller.common.utils import replace_resource_uri
from quantnet_controller.core import AbstractDatabase, DBmodel


logger = logging.getLogger(__name__)
log_format = \
    '%(asctime)s - %(name)s - {%(filename)s:%(lineno)d} - [%(threadName)s] - %(levelname)s - %(message)s'
logging.basicConfig(handlers=[logging.StreamHandler()], format=log_format, force=True)


class QuantnetTest():
    def setup(self):
        global logger
        self._log = logger
        self._test_dburi = os.getenv("QUANTNET_TEST_DBURI", Constants.DEFAULT_TEST_DB_URI)

        self._node_path = os.path.normpath(
            os.path.join(quantnet_mq.schema.__path__[0], "examples/topology"))

        self._node_configs = ["conf_lbnl-q.json",
                              "conf_lbnl-bsm.json"]

        try:
            dburi = global_config.get("database", "default")
            dburi = replace_resource_uri(dburi, Constants.DEFAULT_TEST_DB_NAME)
            global_config.set("database", "default", dburi)
        except Exception:
            global_config.set("database", "default", self._test_dburi)

        self._db = AbstractDatabase()
        self._db.drop_database()

    def add_nodes(self):
        for node in self._node_configs:
            fname = os.path.join(self._node_path, node)
            fp = open(fname)
            data = json.load(fp)
            self._db.add(DBmodel.Node, data)

    @property
    def db(self):
        return self._db
