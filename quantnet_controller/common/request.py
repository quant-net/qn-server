import asyncio
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Optional, List

from quantnet_mq import Code
from quantnet_mq.schema.models import Status, experiment

from quantnet_controller.common.request_translator import RequestTranslator
from quantnet_controller.common.utils import generate_uuid
from quantnet_controller.core import AbstractDatabase as DB, DBmodel


logger = logging.getLogger(__name__)


class RequestType(Enum):
    EXPERIMENT = "experiment"
    CALIBRATION = "calibration"
    SIMULATION = "simulation"
    PROTOCOL = "protocol"  # For generic protocol requests


@dataclass
class RequestParameter:
    """Quant‑Net RequestParameter"""

    exp_name: Optional[str] = None
    path: Optional[List[str]] = field(default_factory=list)
    exp_params: Optional[Dict[str, Any]] = field(default_factory=dict)


@dataclass
class Request:
    """First-class object to track all requests in the system."""

    # Constructor parameters - store serialized data
    # payload_data: Optional[Dict[str, Any]]
    request_type: RequestType
    parameters: Dict[str, Any] = field(default_factory=dict)
    rid: Optional[str] = None

    # Auto-generated fields (not in constructor)
    id: str = field(init=False)
    type: str = field(init=False)  # Store enum value as string
    created_at: float = field(init=False)  # Store as timestamp
    updated_at: float = field(init=False)  # Store as timestamp
    status: Status = field(init=False)  # Use Status from quantnet_mq
    result: Dict[str, Any] = field(default_factory=dict, init=False)
    error: Optional[str] = field(default=None, init=False)

    def __post_init__(self):
        """Initialize auto-generated fields after dataclass init."""
        self.id = self.rid if self.rid is not None else generate_uuid()
        self.type = self.request_type.value if isinstance(self.request_type, Enum) else str(self.request_type)
        now = datetime.now(timezone.utc)
        self.created_at = now.timestamp()
        self.updated_at = self.created_at
        self.status = Status(code=Code.OK.value, value=Code.OK.name, message="Request created, not yet started")
        # Store func as private attribute (not part of dataclass)
        self._func = None
        self._payload = None

    def add_result(self, key, value):
        """
        Add a result entry directly to the result dictionary.

        Args:
            key: Result key (e.g., agent_id, 'error', 'metadata')
            value: Result value
        """
        self.result[key] = value

    def update_status(self, code: Code, error=None):
        """
        Update the request's status and optional error information.

        :param status: New status string (e.g., ``created``, ``queued``, ``executing``,
                       ``completed``, ``failed``)
        :type status: str
        :param error: Optional error message to record when status is ``failed``
        :type error: str | None

        :returns: None
        """
        self.updated_at = datetime.now(timezone.utc).timestamp()

        # Create status object from Code using quantnet_mq Status
        self.status = Status(
            code=code.value, value=code.name, reason=error if error else None, message=error if error else None
        )

        if error:
            self.error = error
            # Store errors in a flat list without nesting
            if "errors" not in self.result:
                self.result["errors"] = []
            self.result["errors"].append(
                {"timestamp": datetime.fromtimestamp(self.updated_at, tz=timezone.utc).isoformat(), "error": str(error)}
            )

    def to_dict(self):
        """Convert Request to dictionary using native dataclass serialization."""
        data = asdict(self)
        # Remove internal fields that shouldn't be serialized
        data.pop("request_type", None)
        data.pop("rid", None)
        # data.pop("func", None)
        # Rename payload_data to payload for consistency
        # data["payload"] = data.pop("payload_data", None)
        # Convert Status object to dict using its serialize method
        data["status"] = json.loads(self.status.serialize())
        return data

    @property
    def func(self) -> Optional[Callable]:
        """Get the callable function."""
        return getattr(self, "_func", None)

    @func.setter
    def func(self, value: Optional[Callable]) -> None:
        """Set the callable function."""
        self._func = value

    @property
    def payload(self):
        """Get the callable function."""
        return getattr(self, "_payload", None)

    @payload.setter
    def payload(self, value):
        """Set the callable function."""
        self._payload = value


class RequestManager:
    """
    Manage :class:`Request` objects using a singleton registry per plugin configuration.

    This class provides global request tracking while allowing each plugin to maintain
    its own request type and optional experiment translator.

    :cvar _instances: Mapping of ``plugin_key`` to ``RequestManager`` instances.
    :type _instances: dict[str, RequestManager]
    :cvar _lock: Asyncio lock protecting singleton creation.
    :type _lock: asyncio.Lock
    :cvar _shared_db_handler: Shared database handler for all managers.
    :type _shared_db_handler: Any
    :cvar _shared_active_requests: In‑memory store of active :class:`Request` objects.
    :type _shared_active_requests: dict[str, Request]
    """

    _instances = {}  # Plugin-specific instances: {plugin_key: RequestManager}
    _lock = asyncio.Lock()
    _shared_db_handler = None  # Shared DB handler for all requests
    _shared_active_requests = {}  # Shared in-memory tracking: {rid: Request}

    def __new__(cls, ctx, plugin_schema=None, request_type=RequestType.PROTOCOL, dbname=None, exp_def_path=None):
        """
        Create or retrieve the singleton :class:`RequestManager` instance for a given
        plugin configuration.

        :param ctx: Execution context passed from the server or client.
        :type ctx: Any
        :param plugin_schema: Optional plugin schema class used to differentiate managers.
        :type plugin_schema: type | None
        :param request_type: Type of request this manager will handle.
        :type request_type: RequestType
        :param dbname: Unused placeholder for compatibility with older APIs.
        :type dbname: str | None
        :param exp_def_path: Optional path to an experiment definition file.
        :type exp_def_path: str | None

        :returns: The singleton :class:`RequestManager` instance associated with the
                  ``plugin_schema`` and ``request_type``.
        :rtype: RequestManager
        """
        # Create a unique key for this plugin configuration
        plugin_key = f"{plugin_schema.__name__ if plugin_schema else 'default'}_{request_type.value}"

        if plugin_key not in cls._instances:
            instance = super().__new__(cls)
            cls._instances[plugin_key] = instance
            instance._initialized = False

        return cls._instances[plugin_key]

    def __init__(self, ctx, plugin_schema=None, request_type=RequestType.PROTOCOL, dbname=None, exp_def_path=None):
        """
        Initialise the :class:`RequestManager` for the specified plugin configuration.
        This method is idempotent – subsequent calls for the same configuration
        will return the already‑initialised instance.

        :param ctx: Execution context.
        :type ctx: Any
        :param plugin_schema: Optional plugin schema class.
        :type plugin_schema: type | None
        :param request_type: The request type this manager will service.
        :type request_type: RequestType
        :param dbname: Placeholder for legacy database name arguments.
        :type dbname: str | None
        :param exp_def_path: Path to experiment definition file, if required.
        :type exp_def_path: str | None

        :returns: ``None``
        """
        # Only initialize once per plugin configuration
        if self._initialized:
            return

        self.ctx = ctx
        self.plugin_schema = plugin_schema
        self.request_type = request_type
        self._request_queue = asyncio.Queue()

        # Initialize shared DB handler once (class-level)
        if RequestManager._shared_db_handler is None:
            RequestManager._shared_db_handler = DB().handler(DBmodel.Request)
            # Create indices on id and type for fast queries
            # RequestManager._shared_db_handler.create_index("id")
            # RequestManager._shared_db_handler.create_index("type")

        # Use shared DB handler and active requests
        self.db_handler = RequestManager._shared_db_handler
        self._active_requests = RequestManager._shared_active_requests

        # Initialize translator for experiment-type requests
        if request_type == RequestType.EXPERIMENT or request_type == RequestType.CALIBRATION:
            if exp_def_path is None:
                import inspect

                # Get the caller's frame to find exp_def_path
                caller_frame = inspect.currentframe().f_back
                caller_file = caller_frame.f_globals.get("__file__")
                if caller_file:
                    caller_dir = os.path.dirname(os.path.abspath(caller_file))
                    exp_def_path = os.path.join(caller_dir, "experiment.py")

            self.translator = RequestTranslator(self.ctx, experiment)
            if exp_def_path and os.path.exists(exp_def_path):
                self.translator.load_exp_def(exp_def_path)
                logger.info(f"Loaded experiment definition from {exp_def_path}")
            else:
                logger.warning(f"Experiment definition not found at {exp_def_path}")
        else:
            self.translator = None

        self._initialized = True
        logger.info(
            f"Initialized RequestManager for {self.plugin_schema.__name__ if self.plugin_schema else 'default'}"
            f" with type {self.request_type.value}"
        )

    @classmethod
    def get_instance(cls, plugin_schema=None, request_type=RequestType.PROTOCOL):
        """
        Retrieve a previously‑created :class:`RequestManager` instance for a given
        plugin configuration.

        :param plugin_schema: Optional plugin schema class used to differentiate managers.
        :type plugin_schema: type | None
        :param request_type: The request type this manager handles.
        :type request_type: RequestType

        :returns: The matching :class:`RequestManager` instance, or ``None`` if it has
                  not been instantiated yet.
        :rtype: RequestManager | None
        """
        plugin_key = f"{plugin_schema.__name__ if plugin_schema else 'default'}_{request_type.value}"
        return cls._instances.get(plugin_key)

    @classmethod
    def get_all_active_requests(cls):
        """
        Return a mapping of all currently active :class:`Request` objects across
        every plugin manager.

        :returns: Dictionary where the key is the request ID and the value is the
                  corresponding :class:`Request` instance.
        :rtype: dict[str, Request]
        """
        return cls._shared_active_requests

    def new_request(self, payload, parameters=None, rid=None, func=None):
        """
        Create and register a new :class:`~quantnet_controller.common.request.Request`.

        :param payload: Plugin‑defined request schema (e.g., ``spgRequest`` instance)
                        containing plugin‑specific data such as nodes, rate, duration, …
        :type payload: Any
        :param parameters: Optional execution parameters for the request type
                           (e.g., ``exp_name``, file system ``path`` for experiments)
        :type parameters: dict | None
        :param rid: Optional request identifier; a UUID will be generated if omitted
        :type rid: str | None
        :param func: Optional custom async callable for ``PROTOCOL`` requests.
                     Signature should be ``async def func(request: Request) -> Code``.
        :type func: Callable[[Request], Awaitable[Code]] | None

        :returns: The newly created :class:`Request` instance, already stored in the
                  in‑memory registry and persisted to the database.
        :rtype: Request
        """
        # payload_data = json.loads(payload.serialize())

        request = Request(request_type=self.request_type, parameters=asdict(parameters), rid=rid)
        request.func = func  # Set func as private attribute after creation
        request.payload = payload

        # Store in shared memory and DB
        self._active_requests[request.id] = request
        self.db_handler.add(request.to_dict())

        logger.info(f"Created new request {request.id} of type {self.request_type}")
        return request

    async def get_request(self, rid, include_result=False, raw=False):
        """
        Retrieve a :class:`Request` instance by its identifier.

        :param rid: Unique request identifier
        :type rid: str
        :param include_result: When ``True`` and the request has completed, also fetch
                               the associated experiment result
        :type include_result: bool
        :param raw: When ``True``, return the raw database record instead of a Request object
        :type raw: json

        :returns: The matching :class:`Request` object, or ``None`` if the identifier is
                  unknown
        :rtype: Request | None
        """
        # Check in-memory first (shared across all instances)
        if rid in self._active_requests:
            req = self._active_requests[rid]
        else:
            # Fall back to DB
            record = self.db_handler.get({"id": rid})
            if record:
                if raw:
                    return record
                # Reconstruct Request from DB
                req = Request(
                    request_type=RequestType(record["type"]),
                    parameters=record.get("parameters", {}),
                    rid=record["id"],
                )
                req.payload = record.get("payload")
                # Restore status object
                if isinstance(record["status"], dict):
                    req.status = Status(
                        code=record["status"]["code"],
                        value=record["status"]["value"],
                        reason=record["status"].get("reason"),
                        message=record["status"].get("message"),
                    )
                else:
                    # Fallback for old format
                    req.status = Status(code=Code.UNKNOWN.value, value=Code.UNKNOWN.name)

                req.result = record["result"] if include_result else {}
                req.error = record.get("error")
                req.created_at = record["created_at"]
                req.updated_at = record["updated_at"]

                # Add back to shared memory
                self._active_requests[rid] = req
            else:
                return None

        return req

    async def find_requests(self, raw=False, filter={}, **kwargs):
        """
        Locate requests that satisfy the provided filter criteria.

        :param filters: Arbitrary keyword filters mapping field names to desired values
                         (e.g., ``type="experiment"``, ``status="queued"``)
        :type filters: Any

        :returns: List of matching :class:`Request` instances
        :rtype: list[Request]
        """
        if filter:
            kwargs["filter"] = filter
        records = self.db_handler.find(**kwargs)
        if raw:
            return records
        requests = []
        for record in records:
            # Check if already in memory
            rid = record["id"]
            if rid in self._active_requests:
                requests.append(self._active_requests[rid])
            else:
                request = Request(
                    request_type=RequestType(record["type"]),
                    parameters=record.get("parameters", {}),
                    rid=rid,
                )
                request.payload = record.get("payload")
                # Restore status object
                if isinstance(record["status"], dict):
                    request.status = Status(
                        code=record["status"]["code"],
                        value=record["status"]["value"],
                        reason=record["status"].get("reason"),
                        message=record["status"].get("message"),
                    )
                else:
                    # Fallback for old format
                    request.status = Status(code=Code.UNKNOWN.value, value=Code.UNKNOWN.name)

                request.result = record.get("result", {})
                request.error = record.get("error")
                request.created_at = record["created_at"]
                request.updated_at = record["updated_at"]

                requests.append(request)
        return requests

    def del_request(self, rid):
        """
        Remove a request from both in‑memory tracking and persistent storage.

        :param rid: Unique request identifier
        :type rid: str

        :returns: ``True`` if the request was successfully deleted, ``False`` otherwise
        :rtype: bool
        """
        # Remove from shared memory
        if rid in self._active_requests:
            del self._active_requests[rid]

        # Remove from DB
        result = self.db_handler.delete({"id": rid})
        logger.info(f"Deleted request {rid}")
        return result > 0

    async def noSchedule(self, request, blocking=True):
        """
        Execute a request immediately without placing it on the queue.

        :param request: The :class:`Request` to be executed
        :type request: Request
        :param blocking: If ``True`` the coroutine waits for the request to finish;
                         if ``False`` a ``Future`` is returned instead
        :type blocking: bool

        :returns: Execution result code
        :rtype: Code
        """
        request.update_status(Code.OK)
        self.db_handler.upsert({"id": request.id}, request.to_dict())

        if blocking:
            return await self._execute_request(request)
        else:
            fut = self._execute_request(request)
            logger.info(f"Request {request.id} added to non-blocking execution")
            return fut

    async def schedule(self, request, blocking=True):
        """
        Enqueue a request for later execution.

        :param request: The :class:`Request` to be queued
        :type request: Request
        :param blocking: ``True`` to wait for the request to complete,
                         ``False`` to obtain a ``Task`` that can be awaited later
        :type blocking: bool

        :returns: ``Code`` on blocking execution, otherwise an ``asyncio.Task`` instance
        :rtype: Code | asyncio.Task
        """
        request.update_status(Code.QUEUED)
        self.db_handler.upsert({"id": request.id}, request.to_dict())
        await self._request_queue.put(request)
        logger.info(f"Request {request.id} added to queue")

        # Create a future that will be resolved when this specific request completes
        request_future = asyncio.Future()

        # Wrapper that processes queue and resolves the future for this request
        async def execution_wrapper():
            try:
                # Process the queue (this will execute our request among others)
                await self.process_queue()

                # Wait for this specific request to complete
                while request.status.code == Code.QUEUED.value:
                    await asyncio.sleep(0.1)  # Poll every 100ms

                # Use the status code directly
                result = Code(request.status.code)

                request_future.set_result(result)
                return result
            except Exception as e:
                logger.error(f"Execution wrapper failed for request {request.id}: {e}")
                request_future.set_exception(e)
                raise

        # Create task for the wrapper
        task = asyncio.create_task(execution_wrapper())

        if blocking:
            # Wait for completion and return result
            return await task
        else:
            # Return the task so caller can await it later
            return task

    async def _execute_request(self, request):
        """
        Dispatch execution logic based on the manager's request type.

        :param request: The :class:`Request` to be executed
        :type request: Request

        :returns: Normalised execution result code
        :rtype: Code
        """
        request.update_status(Code.OK)
        self.db_handler.upsert({"id": request.id}, request.to_dict())

        try:
            if (
                self.request_type == RequestType.EXPERIMENT or self.request_type == RequestType.CALIBRATION
            ) and self.translator:
                # Merge payload data into parameters for experiment execution
                exec_params = request.parameters.copy()
                exec_params["id"] = request.id

                # Execute experiment with result callback
                # Uses request.add_result to ensure flat structure
                rc = await self.translator.start_experiment(exec_params, handle_result=request.add_result)

            elif self.request_type == RequestType.PROTOCOL and request.func:
                # Execute custom protocol function
                logger.info(f"Executing custom function for protocol request {request.id}")
                rc = await request.func(request.payload)

            else:
                # No execution logic defined, just mark as completed
                logger.info(f"No execution logic for request {request.id}, marking as completed")
                rc = Code.OK

            # Normalize return value to Code
            rc = self._normalize_return_code(rc)

            if rc != Code.OK:
                request.update_status(Code.FAILED, f"Execution failed with code {rc}")
            else:
                request.update_status(Code.OK)

            self.db_handler.upsert({"id": request.id}, request.to_dict())
            return rc

        except Exception as e:
            logger.error(f"Request {request.id} execution failed: {e}")
            import traceback

            traceback.print_exc()
            request.update_status(Code.FAILED, str(e))
            self.db_handler.upsert({"id": request.id}, request.to_dict())
            return Code.FAILED

    def _normalize_return_code(self, rc):
        """
        Convert a heterogeneous return value into a :class:`quantnet_mq.Code` enum.

        :param rc: Value returned by the user‑provided execution function. May be a
                   :class:`Code` instance, ``int``, ``bool``, ``str`` or ``None``.
        :type rc: Any

        :returns: Corresponding :class:`Code` enum member
        :rtype: Code
        """
        # Already a Code object
        if isinstance(rc, Code):
            return rc

        # Boolean: True = OK, False = FAILED
        if isinstance(rc, bool):
            return Code.OK if rc else Code.FAILED

        # Integer: 0 = OK, non-zero = FAILED
        if isinstance(rc, int):
            return Code.OK if rc == 0 else Code.FAILED

        # String: try to match Code enum values
        if isinstance(rc, str):
            try:
                return Code[rc.upper()]
            except (KeyError, AttributeError):
                # If string doesn't match any Code, treat as FAILED
                logger.warning(f"Unknown return code string '{rc}', treating as FAILED")
                return Code.FAILED

        # None: treat as OK (function completed without explicit return)
        if rc is None:
            return Code.OK

        # Any other type: log warning and treat as OK if truthy, FAILED if falsy
        logger.warning(f"Unexpected return type {type(rc).__name__}: {rc}, converting to Code")
        return Code.OK if rc else Code.FAILED

    async def process_queue(self):
        """
        Consume all pending requests from the internal queue and execute them sequentially.

        :returns: ``Code.OK`` when the queue has been fully processed
        :rtype: Code
        """
        while not self._request_queue.empty():
            request = await self._request_queue.get()
            logger.info(f"Processing queued request {request.id}")
            await self._execute_request(request)
        return Code.OK

    async def get_experiment_result(self, id, timeout=60):
        """
        Retrieve the result of an experiment request from the translator.

        :param id: Identifier of the experiment request
        :type id: str
        :param timeout: Maximum time (seconds) to wait for the result
        :type timeout: int

        :returns: Experiment result object, or ``None`` if unavailable
        :rtype: Any
        """
        if self.translator:
            return await self.translator.get_experiment_result(id, timeout)
        return None
