"""Console script for quantnet_controller."""
import sys
import click
import asyncio

from quantnet_controller.common.logging import setup_logging
from quantnet_controller.server import QuantnetServer as Quantnet
from quantnet_controller.common.config import Config
from quantnet_controller.core.abstractdatabase import AbstractDatabase as DB
from quantnet_controller.db.broker import SqlaBroker

STARTUP_FAILURE = 3

STOP = asyncio.Event()


def ask_exit(*args):
    STOP.set()


@click.command(help="Run a QUANT-NET Controller instance")
@click.option(
    "--mq-broker-host",
    "mq_broker_host",
    type=str,
    help="Specify the message queue broker host",
    show_default=True,
)
@click.option(
    "--mq-broker-port",
    "mq_broker_port",
    type=int,
    help="Specify the message queue broker port",
    show_default=True,
)
@click.option(
    "--mq-mongo-host",
    "mq_mongo_host",
    type=str,
    help="Specify a MongoDB host (if mongo configured)",
    show_default=True,
)
@click.option(
    "--mq-mongo-port",
    "mq_mongo_port",
    type=int,
    help="Specify a MongoDB port (if mongo configured)",
    show_default=True,
)
@click.option(
    "--plugin-path",
    "plugin_path",
    type=str,
    help="Specify a path containing controller plugins",
    show_default=True
)
@click.option(
    "--schema-path",
    "schema_path",
    type=str,
    help="Specify a path containing additional schema files",
    show_default=True
)
@click.option(
    "-c",
    "--config",
    "config_file",
    type=str,
    default=None,
    help="Specify a configuration file",
    show_default=True
)
def main(
    config_file,
    mq_broker_host,
    mq_broker_port,
    mq_mongo_host,
    mq_mongo_port,
    plugin_path,
    schema_path
) -> None:
    run(
        config_file,
        mq_broker_host,
        mq_broker_port,
        mq_mongo_host,
        mq_mongo_port,
        plugin_path,
        schema_path
    )


def run(
    config_file,
    mq_broker_host,
    mq_broker_port,
    mq_mongo_host,
    mq_mongo_port,
    plugin_path,
    schema_path
) -> None:
    # Create config
    config = Config(
        config_file=config_file,
        mq_broker_host=mq_broker_host,
        mq_broker_port=mq_broker_port,
        mq_mongo_host=mq_mongo_host,
        mq_mongo_port=mq_mongo_port,
        plugin_path=plugin_path,
        schema_path=schema_path
    )

    if not config.config_file:
        import logging
        logging.getLogger(__name__).warning(
            "No configuration file found, continuing with defaults.\n"
            "\tThe quant-net server looks in the following directories for a configuration file, in order:\n"
            "\t(1) --config CLI argument\n"
            "\t(2) $QUANTNET_HOME/etc/quantnet.cfg\n"
            "\t(3) /opt/quantnet/etc/quantnet.cfg"
        )

    setup_logging()

    db_broker = DB().get_broker()
    if isinstance(db_broker, SqlaBroker):
        print("Error: SQLAlchemy DB broker is not supported. Please use MongoDB.")
        sys.exit(STARTUP_FAILURE)

    # Create and start the controller
    quantnet = Quantnet(config)
    quantnet.run()

    # Exit if failed
    if not quantnet.started:
        sys.exit(STARTUP_FAILURE)


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
