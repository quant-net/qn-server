"""
Get the confiugration file from /opt/quantnet/etc/quantnet.cfg
"""

import os
import logging
from datetime import timedelta
from quantnet_controller.common.constants import Constants

try:
    import ConfigParser
except ImportError:
    import configparser as ConfigParser

log = logging.getLogger(__name__)


def config_get(section, option, raise_exception=True, default=None, check_config_table=True):
    """
        Return the string value for a given option in a section

        :param section: the named section.
        :param option: the named option.
        :param raise_exception: Boolean to raise or not NoOptionError or NoSectionError.
        :param default: the default value if not found.
        :param check_config_table: if not set, avoid looking at config table
    .
        :returns: the configuration value.
    """
    try:
        return __CONFIG.get(section, option)
    except (ConfigParser.NoOptionError, ConfigParser.NoSectionError) as err:
        if raise_exception and default is None:
            raise err
        return default


def config_set(section, option, value, raise_exception=True):
    try:
        return __CONFIG.set(section, option, value)
    except ConfigParser.NoSectionError:
        __CONFIG.add_section(section)
        return __CONFIG.set(section, option, value)


__CONFIG = ConfigParser.ConfigParser(os.environ)

__CONFIGFILES = list()
for i in ["QUANTNET_HOME", "VIRTUAL_ENV"]:
    if i in os.environ:
        __CONFIGFILES.append(f"{os.environ[i]}/config/quantnet.cfg")
__CONFIGFILES.append("/opt/quantnet/etc/quantnet.cfg")

__HAS_CONFIG = False
for configfile in __CONFIGFILES:
    __HAS_CONFIG = __CONFIG.read(configfile) == [configfile]
    if __HAS_CONFIG:
        break

if not __HAS_CONFIG:
    log.warning(
        "No configuration file found, continuing with defaults"
        "\n\tThe quant-net server looks in the following directories for a configuration file, in order:"
        "\n\t${QUANTNET_HOME}/etc/quantnet.cfg"
        "\n\t/opt/quantnet/etc/quantnet.cfg"
        "\n\t${VIRTUAL_ENV}/etc/quantnet.cfg"
    )


class Config:
    def __init__(
        self,
        mq_broker_host: str = None,
        mq_broker_port: int = None,
        mq_mongo_host: str = None,
        mq_mongo_port: int = None,
        plugin_path: str = None,
        schema_path: str = None,
        config_path: str = None
    ):
        if mq_broker_host:
            self.mq_broker_host = mq_broker_host
        else:
            self.mq_broker_host = config_get("mq", "host", default="127.0.0.1")
        if mq_broker_port:
            self.mq_broker_port = mq_broker_port
        else:
            self.mq_broker_port = config_get("mq", "port", default="1883")
        if mq_mongo_host:
            self.mq_mongo_host = mq_mongo_host
        else:
            self.mq_mongo_host = config_get("mq", "mongo_host", default="127.0.0.1")
        if mq_mongo_port:
            self.mq_mongo_port = mq_mongo_port
        else:
            self.mq_mongo_port = config_get("mq", "mongo_port", default="27017")

        self.rpc_server_topic = config_get("mq", "rpc_server_topic", default="rpc/qn-server")
        self.rpc_client_topic = config_get("mq", "rpc_client_topic", default="rpc")
        self.rpc_client_name = config_get("mq", "rpc_client_name",
                                          default=f"qn-server-{Constants.INSTANCE_UUID}")
        self.exp_def_path = config_get("experiment_definition", "path",
                                       default=Constants.DEFAULT_EXP_DEFS)
        self.schmanager_grace_period = timedelta(
                milliseconds=int(config_get("schedule_manager", "grace_period", default=50))
            )
        self.scheduler = config_get("scheduling", "name", default=Constants.DEFAULT_SCHEDULER)
        self.router = config_get("routing", "name", default=Constants.DEFAULT_ROUTER)
        self.monitor = config_get("monitoring", "name", default=Constants.DEFAULT_MONITOR)

        if plugin_path:
            self.plugin_path = [Constants.PLUGIN_PATH, plugin_path]
        else:
            try:
                self.plugin_path = [Constants.PLUGIN_PATH, config_get("plugins", "path")]
            except Exception:
                self.plugin_path = [Constants.PLUGIN_PATH]
        if schema_path:
            self.schema_path = schema_path
        else:
            try:
                self.schema_path = config_get("schemas", "path")
            except Exception:
                self.schema_path = None
