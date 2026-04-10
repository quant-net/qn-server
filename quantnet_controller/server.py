"""
Main module.
"""

import asyncio
import os
import sys
import signal
import logging
import uvloop
import importlib
import inspect
from typing import Optional
from types import FrameType
from quantnet_mq.msgserver import MsgServer
from quantnet_mq.msgclient import MsgClient
from quantnet_mq.rpcserver import RPCServer
from quantnet_mq.rpcclient import RPCClient
from quantnet_controller.core.managers import ResourceManager, ControllerContextManager
from quantnet_controller.common.plugin import SchedulingPlugin, RoutingPlugin, MonitoringPlugin, ProtocolPlugin
from quantnet_controller.common.config import Config
from quantnet_controller.common.constants import Constants
from quantnet_mq.schema.models import Schema


logger = logging.getLogger(__name__)
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


class QuantnetServer:
    def __init__(self, config: Config) -> None:
        self.started = False
        self.should_exit = False
        self.force_exit = False
        self._dispatchers = {}
        self._params = {}
        self.ctx = ControllerContextManager(config=config)

        # Create resource manager
        self.ctx.rm = ResourceManager(config=self.ctx.config)

        # Setup RPC client
        self.ctx.rpcclient = RPCClient(
            config.rpc_client_name, topic="rpc/server", host=config.mq_broker_host, port=config.mq_broker_port
        )

    def load_schema(self, path):
        if path:
            Schema.load_schema(path)
        logger.info(f"Server started with protocol namespaces:\n{Schema()}")

    def load_modules(self, ns, path):
        module_spec = importlib.util.spec_from_file_location(ns, path)
        modules = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(modules)
        return modules

    def load_plugins(self, plugin_path):
        def is_plugin_module(module, cls):
            return issubclass(module, cls) and not module == cls

        def fast_scandir(dirname):
            if not dirname:
                return []
            subfolders = [f for f in os.scandir(dirname) if f.is_dir() if f.name != "__pycache__"]
            for dirname in list(subfolders):
                subfolders.extend(fast_scandir(dirname))
            return subfolders

        if isinstance(plugin_path, str):
            plugin_path = [plugin_path]

        self.ctx.protocols = {}

        # Define plugin type mappings
        plugin_mappings = {
            SchedulingPlugin: ("scheduler", lambda module: module.__name__ == self.ctx.config.scheduler),
            RoutingPlugin: ("router", lambda module: module.__name__ == self.ctx.config.router),
            MonitoringPlugin: ("monitor", lambda module: module.__name__ == self.ctx.config.monitor),
            ProtocolPlugin: ("protocols", lambda module: True)
        }

        for path in plugin_path:
            # loading plugins
            for plugin in [f for f in fast_scandir(path) if f.is_dir()]:
                try:
                    sys.path.append(plugin.path)
                    if not os.path.isfile(plugin.path + "/__init__.py"):
                        continue

                    plugin_modules = self.load_modules(os.path.basename(plugin.path), plugin.path + "/__init__.py")

                    for module_name in dir(plugin_modules):
                        module = getattr(plugin_modules, module_name)
                        if not inspect.isclass(module):
                            continue

                        # Check each plugin type with appropriate conditional logic
                        for plugin_type, (attr_name, condition) in plugin_mappings.items():
                            if is_plugin_module(module, plugin_type) and condition(module):
                                if attr_name == "protocols":
                                    self.ctx.protocols[module_name] = module(self.ctx)
                                else:
                                    setattr(self.ctx, attr_name, module(self.ctx))
                                break  # Stop after first match to avoid duplicate loading

                except (ModuleNotFoundError, SyntaxError, NameError) as e:
                    logger.error(f"Problem with module import for {plugin.path}: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Failed to load plugin {plugin} - {e}")
                    continue
                finally:
                    sys.path.remove(plugin.path)

        logger.info("Loaded modules:")
        # register and list all modules
        for _, v in (self.ctx.protocols | self.ctx.plugins).items():
            if v is None:
                continue
            for e in v.get_client_commands():
                self.ctx.rpcclient.set_handler(e[0], e[1], e[2])
            for e in v.get_server_commands():
                self.ctx.rpcserver.set_handler(e[0], e[1], e[2])
            for e in v.get_msg_commands():
                self.ctx.msgserver.subscribe(e[0], e[1])
            print(v)

    def run(self) -> None:
        # self.config.setup_event_loop()
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        return asyncio.run(self.serve())

    async def serve(self) -> None:
        process_id = os.getpid()

        # Install signal handlers
        loop = asyncio.get_event_loop()
        try:
            loop.add_signal_handler(signal.SIGINT, self.handle_exit, signal.SIGINT, None)
            loop.add_signal_handler(signal.SIGTERM, self.handle_exit, signal.SIGTERM, None)
        except NotImplementedError:
            return

        message = "Started server process [%d]"
        logger.info(message % process_id)

        await self.startup()
        if self.should_exit:
            return
        await self.main_loop()
        await self.shutdown()

        message = "Finished server process [%d]"
        logger.info(message % process_id)

    async def startup(self) -> None:

        def _start_plugins():
            self.ctx.scheduler.start() if self.ctx.scheduler else logger.warning("No Scheduler plugin found")
            self.ctx.router.start() if self.ctx.router else logger.warning("No Routing plugin found")
            self.ctx.monitor.start() if self.ctx.monitor else logger.warning("No Monitoring plugin found")

        """Create and startup services of all modules"""
        # Create Msg Server
        self.ctx.msgserver = MsgServer(
            f"msgserver-{Constants.INSTANCE_UUID}",
            host=self.ctx.config.mq_broker_host,
            port=self.ctx.config.mq_broker_port,
        )
        self.ctx.msgclient = MsgClient(
            f"msgclient-{Constants.INSTANCE_UUID}",
            host=self.ctx.config.mq_broker_host,
            port=self.ctx.config.mq_broker_port,
        )
        # Create RPC server
        self.ctx.rpcserver = RPCServer(
            f"rpcserver-{Constants.INSTANCE_UUID}",
            topic=self.ctx.config.rpc_server_topic,
            host=self.ctx.config.mq_broker_host,
            port=self.ctx.config.mq_broker_port,
        )

        # Load any external schema (potentially needed for plugins below)
        self.load_schema(self.ctx.config.schema_path)
        # Load all available plugins
        self.load_plugins(self.ctx.config.plugin_path)

        # Start protocol messaging
        await self.ctx.rpcclient.start()
        await self.ctx.msgclient.start()
        await self.ctx.msgserver.start()
        await self.ctx.rpcserver.start()

        # Change the server status
        self.started = True

        # Start all single-instance plugins
        _start_plugins()

    async def main_loop(self) -> None:
        counter = 0
        should_exit = self.should_exit
        while not should_exit:
            counter += 1
            counter = counter % 864000
            await asyncio.sleep(0.1)
            should_exit = self.should_exit

    async def shutdown(self) -> None:
        logger.info("Shutting down")

        await self.ctx.rpcserver.stop()
        await self.ctx.msgserver.stop()

    def handle_exit(self, sig: int, frame: Optional[FrameType]) -> None:
        if self.should_exit and sig == signal.SIGINT:
            self.force_exit = True
        else:
            self.should_exit = True
