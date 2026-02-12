"""
Resource Manager
"""

import json
import logging
import types
import networkx as nx
from networkx import node_link_data
import quantnet_mq.schema.models as models
from quantnet_controller.common.config import Config
from quantnet_controller.core import AbstractDatabase as DB, DBmodel

logger = logging.getLogger(__name__)


class ResourceManager:
    def __init__(self, rtype="nodes", key="agentId", **kwargs):
        self._topo = None
        self._node_db = DB().handler(DBmodel.Node)
        self._request_db = DB().handler(DBmodel.Request)
        self._is_topo_updated = False
        self._is_topo_full = False

    def node_loader(self, data=None):
        typ = data["systemSettings"]["type"]
        cls = getattr(models, typ)
        return cls(**data)

    def request_cb_wrapper(self, orig_cb):
        """ Capture all requests to the controller """
        async def wrapper(req):
            self._handle_request(req)
            res = orig_cb(req)
            if isinstance(res, types.CoroutineType):
                res = await res
            return res
        return wrapper

    async def handle_register(self, node):
        """ handle registration of node
        """
        if node is None:
            raise Exception(
                f"{ResourceManager.handle_register.__qualname__}: invalid input parameter")

        try:
            payload = node.payload
            sysid = payload.systemSettings.ID
            ntype = payload.systemSettings.type
            logger.info(f'Registering {ntype} {sysid} from agent {node.agentId}')
            jsobj = json.loads(payload.serialize())

            # Save to Database
            self._node_db.upsert({"systemSettings.ID": str(sysid)}, jsobj)
            logger.info(f'Registering {ntype} {sysid} succeed.')
            self._is_topo_updated = True
        except Exception as e:
            logger.warn(f'Registering {ntype} {sysid} failed: {e}')
            raise e

    def find_nodes(self, params=dict(), **kwargs):
        try:
            rdict = kwargs.pop("dict", False)
            nodes = self._node_db.find(filter=params, **kwargs)
            if rdict:
                return nodes
            ret = list()
            for n in nodes:
                ret.append(self.node_loader(n))
            return ret
        except Exception as e:
            raise Exception(
                f"An error occured in find_nodes: {filter}: {e.args}")

    def get_nodes(self, *nnames):
        ret = list()
        for n in nnames:
            node = self._node_db.get({"systemSettings.ID": str(n)})
            if not node:
                raise Exception(f"Node not found: {n}")
            ret.append(self.node_loader(node))
        return ret

    def build_topology(self, full: bool = True):
        color_map = dict()

        def add_node(net, Id, label, group=1, **kwargs):
            node_attrs = {
                'size': 20,
                'title': label,
                'group': group,
                'label': label,
                'shape': 'circle'
            }
            node_attrs.update(kwargs)
            net.add_node(Id, **node_attrs)

        def add_edge(net, src, dst, title=None, dashes=False, arrows='bottom'):
            net.add_edge(src, dst, weight=2, title=title, dashes=dashes,
                         arrows=arrows, color=color_map.get(title))

        g = nx.MultiDiGraph()

        nodes = self.find_nodes()

        channels = dict()
        for n in nodes:
            nid = str(n.systemSettings.ID)

            # Summary statistics always needed
            nu_q = len(n.qubitSettings.qubits) if hasattr(n, 'qubitSettings') and n.qubitSettings and hasattr(n.qubitSettings, 'qubits') else 0
            nu_c = len(n.channels) if hasattr(n, 'channels') and n.channels else 0

            if full:
                # Dump everything from the node definition
                node_data = json.loads(n.serialize())
                add_node(g, nid, nid, nu_q=nu_q, nu_c=nu_c, **node_data)
            else:
                # Summary mode
                add_node(g, nid, nid, 
                         type=str(n.systemSettings.type), 
                         nu_q=nu_q, 
                         nu_c=nu_c)
            # now build a channels map
            channels[nid] = dict()
            if not getattr(n, "channels"):
                logger.error(
                    f"Error: Node {nid} does not have expected channels attribute")
                continue
            for c in n.channels:
                channels[nid][c.ID] = c
        # make edges from channel info
        for k, v in channels.items():
            for cid, c in v.items():
                if c.direction == "out":
                    rid = channels.get(c.neighbor.systemRef)
                    if not rid:
                        logger.warn(f"Warning: {k}: {cid}, could not find remote neighbor \
                        system {c.neighbor.systemRef}")
                        continue
                    rcid = rid.get(c.neighbor.channelRef)
                    if not rcid:
                        logger.warn(f"Warning: {k}: {cid}, could not find remote neighbor channel \
                        {c.neighbor.channelRef}")
                        continue
                    if rcid.direction == "in":
                        add_edge(g, str(k), str(
                            c.neighbor.systemRef), str(c.type))
                    else:
                        logger.error(
                            f"Error: {k}: {cid} out does not match {c.neighbor.systemRef}: {rcid.ID} in")
        self._topo = g

    def get_node_state(self, agentid):
        handler = DB().handler("Monitor")
        res = handler.find(filter={"rid": str(agentid), "eventType": "agentState"},
                           limit=1, sort={"ts": -1})
        return res[0] if res else None

    def get_exp_results(self, exp_id):
        handler = DB().handler("Monitor")
        return handler.find(filter={"exp_id": str(exp_id), "eventType": "experimentResult"})

    def get_topology(self, full: bool = False):
        if not self._topo or self._is_topo_updated or self._is_topo_full != full:
            self.build_topology(full=full)
            self._is_topo_updated = False
            self._is_topo_full = full
        data = node_link_data(self._topo, edges="edges")

        # Calculate summary
        num_qubits = sum(node.get("nu_q", 0) for node in data["nodes"])
        num_channels = sum(node.get("nu_c", 0) for node in data["nodes"])

        return {
            "num_nodes": len(data["nodes"]),
            "num_qubits": num_qubits,
            "num_channels": num_channels,
            "nodes": data["nodes"],
            "edges": data["edges"]
        }


class ControllerContextManager:
    def __init__(self, router=None, scheduler=None, monitor=None, protocols=None,
                 rpcserver=None, rpcclient=None, msgserver=None, msgclient=None,
                 config: Config = None, rm: ResourceManager = None):
        self._plugins = {"router": router, "scheduler": scheduler, "monitor": monitor}
        self._protocols = protocols
        self._rpcserver = rpcserver
        self._rpcclient = rpcclient
        self._msgserver = msgserver
        self._msgclient = msgclient
        self._config = config
        self._rm = rm

    @property
    def config(self) -> Config:
        return self._config

    @property
    def router(self) -> object:
        return self._plugins["router"]

    @router.setter
    def router(self, router: object):
        self._plugins["router"] = router

    @property
    def scheduler(self) -> object:
        return self._plugins["scheduler"]

    @scheduler.setter
    def scheduler(self, scheduler: object):
        self._plugins["scheduler"] = scheduler

    @property
    def monitor(self) -> object:
        return self._plugins["monitor"]

    @monitor.setter
    def monitor(self, monitor: object):
        self._plugins["monitor"] = monitor

    @property
    def plugins(self) -> dict:
        return self._plugins

    @plugins.setter
    def plugins(self, plugins: object):
        self._plugins = plugins

    @property
    def protocols(self) -> dict:
        return self._protocols

    @protocols.setter
    def protocols(self, protocols: object):
        self._protocols = protocols

    def get_protocol(self, name: str) -> object:
        return self._protocols.get(name)

    @property
    def rpcserver(self) -> object:
        return self._rpcserver

    @rpcserver.setter
    def rpcserver(self, rpcserver: object):
        self._rpcserver = rpcserver

    @property
    def rpcclient(self) -> object:
        return self._rpcclient

    @rpcclient.setter
    def rpcclient(self, rpcclient: object):
        self._rpcclient = rpcclient

    @property
    def msgserver(self) -> object:
        return self._msgserver

    @msgserver.setter
    def msgserver(self, msgserver: object):
        self._msgserver = msgserver

    @property
    def msgclient(self) -> object:
        return self._msgclient

    @msgclient.setter
    def msgclient(self, msgclient: object):
        self._msgclient = msgclient

    @property
    def rm(self) -> object:
        return self._rm

    @rm.setter
    def rm(self, rm: object):
        self._rm = rm
