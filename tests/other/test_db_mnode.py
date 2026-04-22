#!/usr/bin/env python3

import os
import logging
import unittest
# import asyncio
import json
import quantnet_mq.schema
from quantnet_controller.common.config import global_config
from quantnet_controller.common.utils import generate_uuid
from quantnet_controller.db.sqla.mnode import add_mnode, mnode_exists, get_mnode, list_mnodes  # del_mnode
# from quantnet_controller.db.sqla.constants import NodeStatus, NodeType

use_sqla = True if "sql" in global_config.get("database", "default", default="") else False

NODE_PATH = os.path.normpath(
    os.path.join(quantnet_mq.schema.__path__[0],
                 "examples/topology"))
NODES = ["conf_lbnl-m.json",
         "conf_ucb-m.json"]


logger = logging.getLogger(__name__)
log_format = \
    '%(asctime)s - %(name)s - {%(filename)s:%(lineno)d} - [%(threadName)s] - %(levelname)s - %(message)s'
logging.basicConfig(handlers=[logging.StreamHandler()], format=log_format, force=True)


class TestMnode(unittest.IsolatedAsyncioTestCase):

    @unittest.skipUnless(use_sqla, "Skipping this test unless use_sqla is True")
    async def test_add_mnode(self):
        for node in NODES:
            id = generate_uuid()
            fname = os.path.join(NODE_PATH, node)
            fp = open(fname)
            data = json.load(fp)
            add_mnode(id=id,
                      system_settings=data['systemSettings'],
                      quantum_settings=data['quantumSettings'],
                      channels=data['channels'])
            assert (mnode_exists(id))

            mnode = get_mnode(id)
            print(json.dumps(mnode, indent=4, sort_keys=False))
            # logger.info(json.dumps(mnode, indent=4, sort_keys=False))
            # del_bsmnode(id)

    @unittest.skipUnless(use_sqla, "Skipping this test unless use_sqla is True")
    async def test_list_mnode(self):
        try:
            mnodes = list_mnodes({})
        except Exception:
            assert (False)
        for mnode in mnodes:
            print(json.dumps(mnode, indent=4, sort_keys=False))
