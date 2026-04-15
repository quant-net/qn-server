# -*- coding: utf-8 -*-

import sqlalchemy

# from dogpile.cache.api import NoValue
from sqlalchemy.dialects.postgresql.base import PGInspector
from sqlalchemy.schema import (
    CreateSchema,
    MetaData,
    Table,
    DropTable,
    ForeignKeyConstraint,
    DropConstraint,
)
from sqlalchemy.sql.ddl import DropSchema

from quantnet_controller.common.config import Config
from quantnet_controller.db.sqla import models
from quantnet_controller.db.sqla.session import get_engine, get_dump_engine


def build_database():
    """Applies the schema to the database. Run this command once to build the database."""
    engine = get_engine()

    schema = Config().get("database", "schema")
    if schema:
        print("Schema set in config, trying to create schema:", schema)
        try:
            with engine.connect() as conn:
                with conn.begin():
                    conn.execute(CreateSchema(schema))
        except Exception as e:
            print("Cannot create schema, please validate manually if schema creation is needed, continuing:", e)

    models.register_models(engine)

    # Put the database under version control
    # alembic_cfg = Config(config_get('alembic', 'cfg'))
    # command.stamp(alembic_cfg, "head")


def dump_schema():
    """Creates a schema dump to a specific database."""
    engine = get_dump_engine()
    models.register_models(engine)


def destroy_database():
    """Removes the schema from the database. Only useful for test cases or malicious intents."""
    engine = get_engine()

    try:
        models.unregister_models(engine)
    except Exception as e:
        print("Cannot destroy schema -- assuming already gone, continuing:", e)


def drop_everything():
    """
    Pre-gather all named constraints and table names, and drop everything.
    This is better than using metadata.reflect(); metadata.drop_all()
    as it handles cyclical constraints between tables.
    Ref. https://github.com/sqlalchemy/sqlalchemy/wiki/DropEverything
    """
    engine = get_engine()

    # the transaction only applies if the DB supports
    # transactional DDL, i.e. Postgresql, MS SQL Server

    with engine.connect() as conn:
        inspector = sqlalchemy.inspect(conn)  # type: Union[Inspector, PGInspector]

        for tname, fkcs in reversed(inspector.get_sorted_table_and_fkc_names(schema="*")):
            if tname:
                drop_table_stmt = DropTable(Table(tname, MetaData(), schema="*"))
                conn.execute(drop_table_stmt)
            elif fkcs:
                if not engine.dialect.supports_alter:
                    continue
                for tname, fkc in fkcs:
                    fk_constraint = ForeignKeyConstraint((), (), name=fkc)
                    Table(tname, MetaData(), fk_constraint)
                    drop_constraint_stmt = DropConstraint(fk_constraint)
                    conn.execute(drop_constraint_stmt)

        schema = Config().get("database", "schema")
        if schema:
            conn.execute(DropSchema(schema, cascade=True))

        if engine.dialect.name == "postgresql":
            assert isinstance(inspector, PGInspector), "expected a PGInspector"
            for enum in inspector.get_enums(schema="*"):
                sqlalchemy.Enum(**enum).drop(bind=conn)
