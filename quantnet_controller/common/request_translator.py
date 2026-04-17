import logging
import json
import time
import asyncio
import importlib
import inspect
from datetime import datetime, timezone, timedelta
from bitarray import bitarray
from collections import Counter

from quantnet_controller.common.experimentdefinitions import Experiment, get_num_timeslot, get_timeslot_mask
from quantnet_controller.common.constants import Constants
from quantnet_controller.common.plugin import Path
from quantnet_mq import Code
from quantnet_mq.schema.models import Parameter

logger = logging.getLogger(__name__)


def _validate_agent_requirements(exp_def, available_nodes, heartbeat_timeout=None):
    """
    Validate that available nodes satisfy experiment requirements.

    Nodes whose ``last_seen`` Unix timestamp is older than *heartbeat_timeout*
    seconds are treated as unavailable and excluded before the type-count check.

    :param exp_def: Experiment definition containing agent sequences.
    :type exp_def: Experiment
    :param available_nodes: List of available nodes from path.
    :type available_nodes: list
    :param heartbeat_timeout: Maximum age in seconds of a node heartbeat before
        it is considered stale.  Defaults to ``Constants.NODE_HEARTBEAT_TIMEOUT``.
    :type heartbeat_timeout: int | float | None

    :returns: Tuple of (is_valid, required_types, available_types, missing_types)
    :rtype: tuple

    :raises ValueError: If validation fails with detailed message about missing agents.
    """
    if heartbeat_timeout is None:
        heartbeat_timeout = Constants.NODE_HEARTBEAT_TIMEOUT

    now = time.time()

    # Filter out nodes that have not sent a heartbeat within the timeout
    reachable_nodes = []
    stale_nodes = []
    for node in available_nodes:
        if isinstance(node, str):
            # String node IDs don't carry last_seen; assume reachable
            reachable_nodes.append(node)
            continue

        last_seen = getattr(node, "last_seen", None)
        if last_seen is None:
            # No heartbeat recorded yet – treat as stale
            node_id = node.systemSettings.ID if hasattr(node, "systemSettings") else str(node)
            stale_nodes.append(node_id)
            logger.warning(f"Node {node_id} has no last_seen timestamp, treating as unavailable")
            continue

        age = now - last_seen
        if age > heartbeat_timeout:
            node_id = node.systemSettings.ID
            stale_nodes.append(node_id)
            logger.warning(
                f"Node {node_id} last seen {age:.1f}s ago "
                f"(timeout={heartbeat_timeout}s), treating as unavailable"
            )
        else:
            reachable_nodes.append(node)

    # Extract required agent types from experiment definition
    required_types = [x.node_type for x in exp_def.agent_sequences]

    # Extract available agent types from reachable nodes only
    available_types = [
        x if isinstance(x, str) else x.systemSettings.type
        for x in reachable_nodes
    ]

    # Count occurrences of each type
    required_counts = Counter(required_types)
    available_counts = Counter(available_types)

    # Find missing agents
    missing_types = []
    for req_type, req_count in required_counts.items():
        avail_count = available_counts.get(req_type, 0)
        if avail_count < req_count:
            missing_types.append({
                'type': req_type,
                'required': req_count,
                'available': avail_count
            })

    is_valid = len(missing_types) == 0

    if not is_valid:
        error_msg = f"Agent validation failed. Missing agents: {missing_types}"
        if stale_nodes:
            error_msg += f" (stale nodes excluded: {stale_nodes})"
        logger.error(error_msg)
        raise ValueError(error_msg)

    logger.debug(f"Agent validation passed. Required: {required_types}, Available: {available_types}")
    return is_valid, required_types, available_types, missing_types


def match_agent_to_exp(exp_def, path, validate=True):
    """
    Match agents from a given path to the requirements of an experiment definition.

    :param exp_def: Experiment definition containing agent sequences.
    :type exp_def: Experiment
    :param path: Path object or list of node IDs representing the route.
    :type path: Any
    :param validate: If True, validate that all required agents are available before matching.
    :type validate: bool

    :returns: List of agent identifiers that satisfy the experiment definition.
    :rtype: list

    :raises ValueError: If validate=True and required agents are not available in the path.
    """
    # Handle both Path objects and lists of node IDs
    if hasattr(path, "hops"):
        nodes = [x for x in path.hops if x is not None and x.systemSettings.type != "OpticalSwitch"] if path.hops else []
    else:
        # If path is already a list (from DB), reconstruct nodes
        nodes = path if isinstance(path, list) else []

    # Validate requirements if requested
    if validate:
        _validate_agent_requirements(exp_def, nodes)

    # Perform matching with non-mutating approach
    mapping = []
    nodes_copy = list(nodes)  # Create copy to avoid mutation
    exp_nodes = [x.node_type for x in exp_def.agent_sequences]
    
    for node_type in exp_nodes:
        for i in range(len(nodes_copy)):
            node_id = nodes_copy[i] if isinstance(nodes_copy[i], str) else nodes_copy[i].systemSettings.ID
            node_type_actual = nodes_copy[i] if isinstance(nodes_copy[i], str) else nodes_copy[i].systemSettings.type

            if node_type == node_type_actual:
                mapping.append(node_id)
                nodes_copy.pop(i)
                break

    logger.info(f"Found agents {mapping}")
    return mapping


class RequestTranslator:
    def __init__(self, context, request_type):
        self.context = context
        self.exp_defs = []
        self.load_exp_def(self.context.config.exp_def_path, True)
        self.lock = asyncio.Lock()
        # Store request_type for DB operations
        self.request_type = request_type

    def load_exp_def(self, path, is_builtin=False):
        """Load experiment definitions from file."""
        module_spec = importlib.util.spec_from_file_location("Experiment", path)
        modules = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(modules)
        for module_name in dir(modules):
            module = getattr(modules, module_name)
            if not inspect.isclass(module):
                continue
            if issubclass(module, Experiment) and module is not Experiment:
                if is_builtin is False:
                    if module_name in [i.__name__ for i in self.exp_defs]:
                        logger.debug(
                            f"Built-in Experiment definition {module_name} is overwritten by external source from "
                            f"{path}"
                        )
                self.exp_defs.append(module)

    def get_experiment_class(self, exp_name):
        """
        Retrieve the experiment class matching the given name.

        :param exp_name: Name of the experiment to locate.
        :type exp_name: str

        :returns: Matching experiment class or ``None`` if not found.
        :rtype: type | None
        """
        for exp in self.exp_defs:
            if exp.name == exp_name:
                logger.info(f"Loading experiment {exp_name}")
                self.visualize_experiment(exp)
                return exp
        logger.error(f"Cannot find request experiment {exp_name} from Experiment Definitions")
        return None

    def visualize_experiment(self, exp_def):
        """
        Log detailed information about an experiment definition for debugging.

        :param exp_def: Experiment definition object.
        :type exp_def: Experiment

        :returns: None
        """
        logger.info("Visualizing Experiment detail")
        print("\n----------------------------------------")
        print(f"{exp_def.name} translates to:")
        for agent_seq in exp_def.agent_sequences:
            print(f"\n{agent_seq.name} for an agent with sequences:")
            for seq in agent_seq.sequences:
                print(f"{seq.name} - duration: {seq.duration / timedelta(microseconds=1)} ms")
        print("----------------------------------------\n")

    async def wait_for_agent_ready(self, agent_id, check_interval=5, timeout=60):
        """
        Wait until the specified agent reports a ``ready`` state.

        :param agent_id: Identifier of the agent to monitor.
        :type agent_id: str
        :param check_interval: Seconds between readiness checks.
        :type check_interval: int
        :param timeout: Maximum seconds to wait before giving up.
        :type timeout: int

        :returns: ``True`` if the agent became ready, ``False`` otherwise.
        :rtype: bool
        """
        start_time = asyncio.get_event_loop().time()
        while True:
            if await self.is_agent_ready(agent_id):
                logger.info(f"Agent {agent_id} is ready.")
                return True
            if asyncio.get_event_loop().time() - start_time > timeout:
                logger.error(f"Timeout waiting for agent {agent_id} to be ready.")
                return False
            logger.info(f"Agent {agent_id} not ready. Waiting {check_interval} seconds...")
            await asyncio.sleep(check_interval)

    async def is_agent_ready(self, agent_id):
        """
        Determine whether the given agent is currently in a ``ready`` state.

        :param agent_id: Identifier of the agent.
        :type agent_id: str

        :returns: ``True`` if the agent's status is ``IN_SPEC``, otherwise ``False``.
        :rtype: bool
        """
        status = self.context.rm.get_node_state(agent_id)
        return status["value"] == "IN_SPEC" if status else False

    async def start_experiment(self, parameters, handle_result=None):
        """
        Start experiment processing.

        :param parameters: Dictionary with request details.
        :type parameters: dict
        :param parameters['id']: Request identifier.
        :type parameters['id']: str
        :param parameters['exp_name']: Name of the experiment to run.
        :type parameters['exp_name']: str
        :param parameters['path']: Path object or list of node IDs.
        :type parameters['path']: Any
        :param parameters['params']: Experiment-specific parameters.
        :type parameters['params']: dict | list | Any
        :param parameters['payload_data']: Optional additional payload data.
        :type parameters['payload_data']: Any | None

        :returns: Code indicating success (Code.OK) or failure (Code.FAILED).
        :rtype: Code
        """
        exp_def = self.get_experiment_class(parameters["exp_name"])
        if exp_def is None:
            return Code.FAILED

        # Get path - handle both Path objects and serialized lists
        path_data = parameters.get("path")

        # Convert to Path object if needed
        if isinstance(path_data, list):
            # Deserialize from node IDs using resource manager to get full node objects
            path = Path.from_node_ids(path_data, resource_manager=self.context.rm)
        elif type(path_data) is Path:
            # Already a Path object
            path = path_data
        else:
            # Handle None or invalid data
            path = Path.from_node_ids(None)

        # Match agents with validation - fail fast if agents don't match
        try:
            agents = match_agent_to_exp(exp_def, path, validate=True)
        except ValueError as e:
            logger.error(f"Agent validation failed for experiment {parameters['id']}: {e}")
            if handle_result:
                handle_result("error", f"Invalid path for experiment: {str(e)}")
            return Code.FAILED

        # Wait for all agents to be ready
        all_agents_ready = True
        for agent_id in agents:
            if not await self.wait_for_agent_ready(agent_id):
                logger.error(f"Agent {agent_id} did not become ready. Skipping experiment {parameters['id']}.")
                all_agents_ready = False
                break

        if not all_agents_ready:
            return Code.FAILED

        try:
            # Get experiment parameters - could come from params or payload_data
            exp_params = parameters.get("exp_params", [])
            # if "payload_data" in parameters:
            #     # Merge payload data if needed
            #     exp_params = {**exp_params, **parameters["payload_data"]}

            rc = await self.translate_request(parameters["id"], exp_def, exp_params, agents, handle_result)
            if rc != Code.OK:
                await self.context.scheduler.cancel_tasks(parameters["id"], agents)
            return rc
        except Exception as e:
            logger.error(f"Experiment translation failed: {e}")
            if handle_result:
                handle_result("error", str(e))
            return Code.FAILED

    async def get_experiment_result(self, id, timeout=60):
        """
        Retrieve the result of a completed experiment.

        :param id: Identifier of the experiment request.
        :type id: str
        :param timeout: Maximum seconds to wait for the result.
        :type timeout: int

        :returns: Experiment result object or ``None`` if unavailable.
        :rtype: Any
        """
        logger.info(f"Getting experiment result for {id}")
        result = self.context.rm.get_exp_results(id)
        return result

    def find_common_slot(self, agent_ids, availabilities, exp_def):
        """
        Determine common timeslots across multiple agents.

        :param agent_ids: List of agent identifiers.
        :type agent_ids: list
        :param availabilities: Mapping of agent IDs to their availability bitarrays.
        :type availabilities: dict
        :param exp_def: Experiment definition containing agent sequences.
        :type exp_def: Experiment

        :returns: Dictionary mapping each agent ID to its allocated slot list.
        :rtype: dict
        """
        logger.info(f"Finding common timeslots from agents {agent_ids}")
        slots = {}

        slot_mask = bitarray(max([get_timeslot_mask(i.sequences) for i in exp_def.agent_sequences]))

        common_bit = bitarray("1" * Constants.MAX_TIMESLOTS)
        for agent_id in agent_ids:
            common_bit = bitarray(availabilities[agent_id]) & common_bit

        start_index = (common_bit).find(slot_mask)

        for i in range(len(exp_def.agent_sequences)):
            agent_sequence = exp_def.agent_sequences[i]
            seq_length = len(get_timeslot_mask(agent_sequence.sequences))
            slot = list(range(start_index, start_index + seq_length))
            slots[agent_ids[i]] = slot
        return slots

    async def get_slots_to_allocate(self, agent_ids, exp_def):
        """
        Compute available timeslots for a set of agents based on the experiment definition.

        :param agent_ids: List of agent identifiers.
        :type agent_ids: list
        :param exp_def: Experiment definition.
        :type exp_def: Experiment

        :returns: Tuple of (start_time, slots_to_allocate) where slots_to_allocate maps agents to slot lists.
        :rtype: tuple
        """
        async with self.lock:
            logger.info("Handling timeslots for agents")
            param = {}
            now = datetime.now(timezone.utc)
            start_time = (now + self.context.config.schmanager_grace_period).timestamp()
            param["startTime"] = start_time
            param["slotSize"] = (Constants.SLOTSIZE).total_seconds()
            param["numSlots"] = Constants.MAX_TIMESLOTS

            availabilities = await self.context.scheduler.get_timeslots(agent_ids, param)
        slots_to_allocate = self.find_common_slot(agent_ids, availabilities, exp_def)

        return start_time, slots_to_allocate

    async def translate_request(self, exp_id, exp, exp_params, agent_ids, handle_result=None):
        """
        Translate a high‑level experiment request into tasks for each agent.

        :param exp_id: Identifier of the experiment request.
        :type exp_id: str
        :param exp: Experiment definition object.
        :type exp: Experiment
        :param exp_params: Parameters to pass to each task.
        :type exp_params: dict
        :param agent_ids: List of agent identifiers.
        :type agent_ids: list

        :returns: ``0`` on success, non‑zero error code on failure.
        :rtype: int
        """

        logger.info(f"translating request: {exp_id}")
        rpc_exp_params = []
        for k, v in exp_params.items():
            rpc_exp_params.append(Parameter(name=k, value=v))

        try:
            start_time, timeslots = await self.get_slots_to_allocate(agent_ids, exp)
            submit_tasks = []

            for idx in range(len(exp.agent_sequences)):
                agent_sequence = exp.agent_sequences[idx]
                agent_id = agent_ids[idx]
                timeslot_mask = timeslots[agent_id]
                logger.info(f"timeslots: {timeslots[agent_id]}")
                allocations = []

                for sequence in agent_sequence.sequences:
                    timeslot = get_num_timeslot(sequence)
                    allocation = {
                        "expName": sequence.name,
                        "className": sequence.class_name,
                        "parameters": rpc_exp_params,
                        "timeSlot": timeslot_mask[:timeslot],
                    }
                    timeslot_mask = timeslot_mask[timeslot:]
                    allocations.append(allocation)
                    logger.info(
                        f"Submitting sequences {sequence.name} to {agent_id} with slot {allocation['timeSlot']}"
                    )

                schedule_params = {
                    "type": "submit",
                    "exp_id": exp_id,
                    "timeslotBase": start_time,
                    "allocations": allocations,
                }
                submit_tasks.append(self.submit(agent_id, schedule_params))

            submit_results = await asyncio.gather(*submit_tasks, return_exceptions=True)
            for idx, result in enumerate(submit_results):
                if isinstance(result, Exception):
                    raise Exception(f"Failed to allocate task to agent {agent_ids[idx]}: {result}")
                if result["status"]["code"] != Code.OK.value:
                    raise Exception(
                        f"Failed to allocate task to agent {agent_ids[idx]}: "
                        f"status {result['status']['code']}"
                    )

            getResult_tasks = [
                self.getResult(agent_id, {"expid": exp_id})
                for agent_id in agent_ids
            ]
            agent_results = await asyncio.gather(*getResult_tasks, return_exceptions=True)
            for idx, result in enumerate(agent_results):
                if isinstance(result, Exception):
                    raise Exception(f"Failed to get result from agent {agent_ids[idx]}: {result}")
                if result["status"]["code"] not in [Code.OK.value, Code.QUEUED.value]:
                    raise Exception(
                        f"Failed to get result from agent {agent_ids[idx]}: "
                        f"status {result['status']['code']}"
                    )

            # Store results directly without nesting - each agent's result is stored by agent_id
            if handle_result:
                for agent_result in agent_results:
                    agent_id = agent_result.get("agentId")
                    if agent_id:
                        # Store each agent's result directly, avoiding nested "result" keys
                        handle_result(agent_id, agent_result)

            logger.info(f"Experiment completed with results from {len(agent_results)} agents")
            return Code.OK
        except Exception as e:
            logger.error(f"Failed to handle timeslot allocation: {e.args[0]}")
            if handle_result:
                handle_result("error", str(e))
            return Code.FAILED

    async def submit(self, agent_id, param, timeout=5.0):
        """
        Submit a task to the specified agent.

        :param agent_id: Identifier of the target agent.
        :type agent_id: str
        :param param: Parameters for the task submission.
        :type param: dict
        :param timeout: Timeout in seconds for the RPC call.
        :type timeout: float

        :returns: Parsed response from the agent.
        :rtype: dict
        """
        logger.debug(f"Submitting function with param {param}")
        submitResp = await self.context.rpcclient.call(
            "experiment.submit",
            param,
            topic=f"rpc/{agent_id}",
            timeout=timeout,
        )
        submitResp = json.loads(submitResp)
        return submitResp

    async def getResult(self, agent_id, param, timeout=600.0):
        """
        Retrieve the result of a previously submitted experiment from the agent.

        :param agent_id: Identifier of the agent.
        :type agent_id: str
        :param param: Dictionary containing the experiment identifier.
        :type param: dict
        :param timeout: Timeout in seconds for the RPC call.
        :type timeout: float

        :returns: Response dictionary with result data.
        :rtype: dict
        """
        logger.debug(f"Getting result of exp {param['expid']}")
        submitResp = await self.context.rpcclient.call(
            "experiment.getResult",
            param,
            topic=f"rpc/{agent_id}",
            timeout=timeout,
        )
        submitResp = json.loads(submitResp)
        submitResp.update({"agentId": str(agent_id)})
        return submitResp
