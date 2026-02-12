import logging
from quantnet_controller.common.plugin import ProtocolPlugin, PluginType
from quantnet_controller.core.managers import ResourceManager
from quantnet_mq import Code
from quantnet_mq.schema.models import (
    agentRegisterResponse,
    agentDeregisterResponse,
    getInfoResponse,
    Status as responseStatus,
)

logger = logging.getLogger(__name__)


class RegisterProtocol(ProtocolPlugin):
    def __init__(self, context):
        super().__init__("agentRegister", PluginType.PROTOCOL, context)

        self._client_commands = [
        ]

        self._server_commands = [
            ("register", self.handle_register, "quantnet_mq.schema.models.agentRegister"),
            ("deregister", self.handle_deregister, "quantnet_mq.schema.models.agentDeregister"),
            ("update", self.handle_update, "quantnet_mq.schema.models.agentUpdate"),
            ("getinfo", self.handle_getinfo, "quantnet_mq.schema.models.getInfo"),
        ]
        self._msg_commands = list()
        self.ctx = context
        self._rm = ResourceManager(config=context.config)

    def initialize(self):
        pass

    def destroy(self):
        pass

    def reset(self):
        pass

    async def handle_register(self, request):
        """handle rpc messages"""
        logger.info(f"Received Register: {request.serialize()}")
        rc = 0
        try:
            await self.ctx.scheduler.schedule(self._rm.handle_register, request)
        except Exception as e:
            rc = 6
            return agentRegisterResponse(status=responseStatus(code=rc, value=Code(rc).name, reason=str(e)))
        return agentRegisterResponse(status=responseStatus(code=rc, value=Code(rc).name))

    def handle_deregister(self, request):
        """handle rpc messages"""
        logger.info(f"Received Deregister: {request.serialize()}")
        rc = 0
        return agentDeregisterResponse(status=responseStatus(code=rc, value=Code(rc).name))

    def handle_update(self, request):
        """handle rpc messages"""
        logger.info(f"Received Update: {request.serialize()}")
        pass

    def handle_getinfo(self, request):
        """handle rpc messages"""
        logger.info(f"Received getInfo: {request.serialize()}")
        rc = 0
        if request.payload.type == "topology":
            full = request.payload.parameters.as_dict().get("full", False)
            return getInfoResponse(status=responseStatus(code=rc, value=Code(rc).name), value=[self._rm.get_topology(full=full)])
        elif request.payload.type == "node":
            nodes = self._rm.find_nodes(request.payload.parameters.as_dict())
            for n in nodes:
                n.state = self._rm.get_node_state(str(n.systemSettings.ID))
            nodes = [n.as_dict() for n in nodes]
            return getInfoResponse(status=responseStatus(code=rc, value=Code(rc).name), value=nodes)
        else:
            raise Exception(f"unknown type {request.payload.type} in getInfo.")

    def handle_generic(self, request):
        """handle rpc messages"""
        logger.info(f"Received Generic Request: {request.serialize()}")
        return agentRegisterResponse(status={"code": 0, "status": "OK"})
