#!/usr/bin/env python3

import os
import logging
import unittest
import json
import quantnet_mq.schema
from quantnet_controller.common.config import global_config
from quantnet_controller.common.utils import generate_uuid
from quantnet_controller.db.sqla.qnode import add_qnode, qnode_exists, get_qnode

use_sqla = True if "sql" in global_config.get("database", "default", default="") else False

NODE_PATH = os.path.normpath(
    os.path.join(quantnet_mq.schema.__path__[0],
                 "examples/topology"))

NODES = ["conf_simplelink-alice.json",
         "conf_simplelink-bob.json"]

logger = logging.getLogger(__name__)
log_format = \
    '%(asctime)s - %(name)s - {%(filename)s:%(lineno)d} - [%(threadName)s] - %(levelname)s - %(message)s'
logging.basicConfig(handlers=[logging.StreamHandler()], format=log_format, force=True)


class TestQnode(unittest.IsolatedAsyncioTestCase):

    @unittest.skipUnless(use_sqla, "Skipping this test unless use_sqla is True")
    async def test_add_node(self):
        for node in NODES:
            id = generate_uuid()

            fname = os.path.join(NODE_PATH, node)
            fp = open(fname)
            data = json.load(fp)
            add_qnode(id,
                      system_settings=data['systemSettings'],
                      qubit_settings=data['qubitSettings'],
                      interface_settings=data['matterLightInterfaceSettings'],
                      channel_settings=data['channels'])
            assert (qnode_exists(id))

            qnode = get_qnode(id)
            print(json.dumps(qnode, indent=4, sort_keys=False))
            # del_qnode(id)
