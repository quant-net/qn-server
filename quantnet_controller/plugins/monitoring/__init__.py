import logging
from quantnet_controller.common.plugin import MonitoringPlugin, PluginType
from quantnet_mq.schema.models import monitor
from quantnet_controller.core import AbstractDatabase as DB

logger = logging.getLogger(__name__)


class Monitor(MonitoringPlugin):
    def __init__(self, context):
        super().__init__("monitor", PluginType.MONITORING, context)
        self._db = DB().handler("Monitor")
        self._msg_commands = [
            ("monitor", self.handle_resource_update)
        ]

    async def handle_resource_update(self, request):
        logger.debug(f"Received resource update: {request}")
        try:
            obj = monitor.MonitorEvent.from_json(request)
            if obj.eventType == "agentHeartbeat":
                # Update node registration and don't save
                pass
            else:
                self._db.add(obj.as_dict())
                if obj.eventType == "agentState":
                    logger.info(f"{obj.rid} {obj.eventType} is updated : "
                                f"{self._context.rm.get_node_state(obj.rid)}")
                elif obj.eventType == "experimentResult":
                    logger.info(f"{obj.rid} {obj.eventType} is updated : {obj.value}")
        except Exception as e:
            logger.warning(f"Failed to update resource : {e}")

    def initialize(self):
        pass

    def destroy(self):
        pass

    def reset(self):
        pass

    def start(self):
        logger.info("Monitor started and listening on /monitor topic")
