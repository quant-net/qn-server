import os
import logging
from datetime import timedelta
from quantnet_controller.common.constants import Constants

try:
    import ConfigParser
except ImportError:
    import configparser as ConfigParser

log = logging.getLogger(__name__)


def find_config_file(cli_config_file=None):
    if cli_config_file:
        if not os.path.exists(cli_config_file):
            import sys
            print(f"Error: Specified configuration file '{cli_config_file}' does not exist.", file=sys.stderr)
            sys.exit(3)
        return cli_config_file

    paths = []
    if "QUANTNET_HOME" in os.environ:
        paths.append(os.path.join(os.environ["QUANTNET_HOME"], "etc", "quantnet.cfg"))

    paths.append("/opt/quantnet/etc/quantnet.cfg")

    for path in paths:
        if os.path.exists(path):
            return path


_CACHED_PARSER = None


class Config:
    def __init__(
        self,
        config_file: str = None,
        mq_broker_host: str = None,
        mq_broker_port: int = None,
        mq_mongo_host: str = None,
        mq_mongo_port: int = None,
        plugin_path: str = None,
        schema_path: str = None,
        config_path: str = None,
    ):
        global _CACHED_PARSER
        self.config_file = find_config_file(config_file)

        if _CACHED_PARSER is None or config_file:
            self._parser = ConfigParser.ConfigParser(os.environ)
            if self.config_file and self._parser.read(self.config_file) == [self.config_file]:
                log.info(f"Loaded configuration from {self.config_file}")

            if _CACHED_PARSER is None or self.config_file:
                _CACHED_PARSER = self._parser
        else:
            self._parser = _CACHED_PARSER

        self.mq_broker_host = self._resolve(mq_broker_host, "mq", "host", "127.0.0.1")
        self.mq_broker_port = self._resolve(mq_broker_port, "mq", "port", "1883")
        self.mq_mongo_host = self._resolve(mq_mongo_host, "mq", "mongo_host", "127.0.0.1")
        self.mq_mongo_port = self._resolve(mq_mongo_port, "mq", "mongo_port", "27017")

        self.rpc_server_topic = self._resolve(None, "mq", "rpc_server_topic", "rpc/qn-server")
        self.rpc_client_topic = self._resolve(None, "mq", "rpc_client_topic", "rpc")
        self.rpc_client_name = self._resolve(None, "mq", "rpc_client_name", f"qn-server-{Constants.INSTANCE_UUID}")

        self.exp_def_path = self._resolve(None, "experiment_definition", "path", Constants.DEFAULT_EXP_DEFS)

        grace_ms = self._resolve(None, "schedule_manager", "grace_period", 50)
        self.schmanager_grace_period = timedelta(milliseconds=int(grace_ms))

        self.scheduler = self._resolve(None, "scheduling", "name", Constants.DEFAULT_SCHEDULER)
        self.router = self._resolve(None, "routing", "name", Constants.DEFAULT_ROUTER)
        self.monitor = self._resolve(None, "monitoring", "name", Constants.DEFAULT_MONITOR)

        if plugin_path:
            self.plugin_path = [Constants.PLUGIN_PATH, plugin_path]
        else:
            cfg_plugin = self._resolve(None, "plugins", "path", None)
            self.plugin_path = [Constants.PLUGIN_PATH, cfg_plugin] if cfg_plugin else [Constants.PLUGIN_PATH]

        self.schema_path = schema_path if schema_path else self._resolve(None, "schemas", "path", None)

    def _resolve(self, cli_val, section, option, default):
        if cli_val is not None:
            return cli_val
        try:
            return self._parser.get(section, option)
        except (ConfigParser.NoOptionError, ConfigParser.NoSectionError):
            return default

    def get(self, section, option, default=None, **kwargs):
        return self._resolve(None, section, option, default)
