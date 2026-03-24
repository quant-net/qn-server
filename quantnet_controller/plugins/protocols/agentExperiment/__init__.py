import logging
import os
from quantnet_controller.common.plugin import ProtocolPlugin, PluginType
from quantnet_controller.common.request import RequestManager, RequestType, RequestParameter, Request
from quantnet_controller.core import AbstractDatabase as DB
from quantnet_mq import Code
from quantnet_mq.schema.models import (
    agentExperiment,
    agentExperimentResponse,
    Status as responseStatus,
)

logger = logging.getLogger(__name__)


class ExperimentProtocol(ProtocolPlugin):
    def __init__(self, context):
        super().__init__("experiment", PluginType.PROTOCOL, context)

        self._client_commands = [
            ("experiment.submit", None, "quantnet_mq.schema.models.experiment.submit"),
            ("experiment.getState", None, "quantnet_mq.schema.models.experiment.getState"),
            ("experiment.getInfo", None, "quantnet_mq.schema.models.experiment.getInfo"),
            ("experiment.setValue", None, "quantnet_mq.schema.models.experiment.setValue"),
            ("experiment.getResult", None, "quantnet_mq.schema.models.experiment.getResult"),
            ("experiment.cancel", None, "quantnet_mq.schema.models.experiment.cancel"),
            ("experiment.cleanUp", None, "quantnet_mq.schema.models.experiment.cleanUp"),
        ]

        self._server_commands = [
            ("agentExperiment", self.handle_experiment, "quantnet_mq.schema.models.agentExperiment"),
        ]
        self._msg_commands = list()
        self.ctx = context

        # Initialize RequestManager with experiment definitions
        exp_def_path = os.path.join(os.path.dirname(__file__), "exp_defs.py")
        self.request_manager = RequestManager(
            context, plugin_schema=agentExperiment, request_type=RequestType.EXPERIMENT, exp_def_path=exp_def_path
        )

    def initialize(self):
        pass

    def destroy(self):
        pass

    def reset(self):
        pass

    async def handle_experiment(self, request):
        """Handle Experiment submission and queries."""

        if request.payload.type == "submit":
            logger.info(f"Received experiment submit request: {request.serialize()}")

            # Create plugin-specific payload object
            payload = agentExperiment(**request)

            # Get agent IDs and find path
            agent_ids = payload.payload.parameters.agentIds
            if len(agent_ids) == 1:
                src = dst = agent_ids[0]
            else:
                src, dst = agent_ids[0:2]

            p = await self.ctx.router.find_path(src, dst)

            # Create experiment execution parameters
            parameters = RequestParameter(
                exp_name=payload.payload.parameters.expName,
                path=p.to_node_ids(),
                exp_params=payload.payload.parameters.expParameters,
            )

            # Create Request object through RequestManager
            # Payload encapsulates the plugin request (agentIds, expName, expParameters)
            req = self.request_manager.new_request(payload=payload, parameters=parameters)

            # Schedule the request (non-blocking, immediate execution)
            rc = await self.request_manager.schedule(req, blocking=False)

            return agentExperimentResponse(
                status=responseStatus(code=rc.value, value=rc.name),
                experiments=[
                    {
                        "phase": "queued",
                        "agentIds": agent_ids,
                        "expName": payload.payload.parameters.expName,
                        "param": payload.payload.parameters.expParameters,
                        "exp_id": req.id,
                    }
                ],
            )

        elif request.payload.type == "get":
            logger.info(f"Received experiment get request: {request.serialize()}")

            payload = agentExperiment(**request)
            params = payload.payload.parameters.as_dict()

            try:
                exp_id = params.get("id")

                # Get experiment using RequestManager
                if exp_id:
                    exp = await self.request_manager.get_request(exp_id, include_result=True, raw=True)
                    if exp:
                        exps = [exp.to_dict()] if isinstance(exp, Request) else [exp]
                    else:
                        exps = []
                else:
                    agent_ids_filter = params.get("agentIds", [])
                    # If "query" is the only id, it means searching all
                    if agent_ids_filter == ["query"]:
                        agent_ids_filter = []

                    exps = await self.request_manager.find_requests(raw=True)
                    
                    if agent_ids_filter:
                        # Filter RequestManager results
                        exps = [e for e in exps if any(aid in agent_ids_filter for aid in (e.get("agent_ids") or e.get("agentIds") or []))]

                # Sort by created_at descending
                exps.sort(key=lambda x: x.get("created_at", 0), reverse=True)

                return agentExperimentResponse(
                    status=responseStatus(code=Code.OK.value, value=Code.OK.name), experiments=exps
                )

            except Exception as e:
                logger.error(f"Failed to get experiment: {e}")
                return agentExperimentResponse(
                    status=responseStatus(
                        code=Code.INVALID_ARGUMENT.value, value=Code.INVALID_ARGUMENT.name, message=f"{e}"
                    ),
                    experiments=[],
                )
        else:
            logger.error(f"Unknown experiment cmd type {request.payload.type}")
            return agentExperimentResponse(
                status=responseStatus(
                    code=Code.INVALID_ARGUMENT.value,
                    value=Code.INVALID_ARGUMENT.name,
                    message=f"Unknown type: {request.payload.type}",
                ),
                experiments=[],
            )
