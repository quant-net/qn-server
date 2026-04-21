import os
import sys
import logging
import logging.config


def quantnet_log_formatter(config):
    config_logformat = config.get(
        "common",
        "logformat",
        default="{asctime} {name:<29} {process} {levelname:>8} {message}",
    )
    return logging.Formatter(fmt=config_logformat, style="{")


def setup_default_logging(config):
    """
    Configures the logging by setting the output stream to stdout and
    configures log level and log format.
    """
    config_loglevel = getattr(logging, config.get("common", "loglevel", default="INFO").upper())

    stdouthandler = logging.StreamHandler(stream=sys.stdout)
    stdouthandler.setFormatter(quantnet_log_formatter(config))
    stdouthandler.setLevel(config_loglevel)
    logging.basicConfig(level=config_loglevel, handlers=[stdouthandler])


def setup_logging(config):
    """
    Configures the logging by setting the output stream to stdout and
    configures log level and log format.
    """

    configfiles = list()

    logging_config_path = config.get("common", "logging_config", default=None)
    if logging_config_path:
        configfiles.append(logging_config_path)

    for i in ["QUANTNET_HOME", "VIRTUAL_ENV"]:
        if i in os.environ:
            configfiles.append(f"{os.environ[i]}/etc/logging.conf")
    configfiles.append("/opt/quantnet/etc/logging.conf")

    has_config = False
    for configfile in configfiles:
        try:
            logging.config.fileConfig(configfile, disable_existing_loggers=False)
            has_config = True
        except Exception as e:
            has_config = False
        if has_config:
            break

    if not has_config:
        setup_default_logging(config)
