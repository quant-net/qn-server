# -*- coding: utf-8 -*-

import datetime
import sys
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    CHAR,
    String as _String,
    event,
    UniqueConstraint,
    LargeBinary
)
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import object_mapper, relationship
from sqlalchemy.schema import ForeignKeyConstraint, PrimaryKeyConstraint, CheckConstraint, Table
from sqlalchemy.types import JSON as Sqla_JSON, ARRAY

from quantnet_controller.common import utils
from quantnet_controller.db.sqla.constants import NodeStatus
from quantnet_controller.db.sqla.session import BASE
from quantnet_controller.db.sqla.types import GUID

# Recipe to force str instead if unicode
# https://groups.google.com/forum/#!msg/sqlalchemy/8Xn31vBfGKU/bAGLNKapvSMJ


def String(*arg, **kw):
    if sys.version_info[0] < 3:
        kw["convert_unicode"] = "force"
    return _String(*arg, **kw)


@compiles(Boolean, "oracle")
def compile_binary_oracle(type_, compiler, **kw):
    return "NUMBER(1)"


@event.listens_for(PrimaryKeyConstraint, "after_parent_attach")
def _pk_constraint_name(const, table):
    const.name = f"{table.name.upper()}_PK"


@event.listens_for(ForeignKeyConstraint, "after_parent_attach")
def _fk_constraint_name(const, table):
    if const.name:
        return
    fk = const.elements[0]
    reftable, refcol = fk.target_fullname.split(".")
    const.name = f"fk_{table.name}_{fk.parent.name}_{reftable}"


@event.listens_for(UniqueConstraint, "after_parent_attach")
def _unique_constraint_name(const, table):
    if const.name:
        return
    const.name = f"uq_{table.name}_{list(const.columns)[0].name}"


@event.listens_for(CheckConstraint, "after_parent_attach")
def _ck_constraint_name(const, table):
    if const.name is None:
        if "DELETED" in str(const.sqltext).upper():
            if len(table.name) > 20:
                const.name = f"{table.name.upper()}_DEL_CHK"
            else:
                const.name = f"{table.name.upper()}_DELETED_CHK"

    if const.name is None:
        const.name = table.name.upper() + "_" + str(uuid.uuid4())[:6] + "_CHK"


@event.listens_for(Table, "after_parent_attach")
def _add_created_col(table, metadata):
    if not table.name.upper():
        pass

    if not table.name.upper().endswith("_HISTORY"):
        if table.info.get("soft_delete", False):
            table.append_column(Column("deleted", Boolean, default=False))
            table.append_column(Column("deleted_at", DateTime))


class ModelBase(object):
    """Base class for Models"""

    __table_initialized__ = False

    @declared_attr
    def __table_args__(cls):
        return cls._table_args + (
            CheckConstraint("CREATED_AT IS NOT NULL", name=cls.__tablename__.upper() + "_CREATED_NN"),
            CheckConstraint("UPDATED_AT IS NOT NULL", name=cls.__tablename__.upper() + "_UPDATED_NN"),
            {"mysql_engine": "InnoDB"},
        )

    @declared_attr
    def created_at(cls):
        return Column("created_at", DateTime, default=datetime.datetime.utcnow)

    @declared_attr
    def updated_at(cls):
        return Column("updated_at", DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    def save(self, flush=True, session=None):
        """Save this object"""
        session.add(self)
        if flush:
            session.flush()

    def delete(self, flush=True, session=None):
        """Delete this object"""
        session.delete(self)
        if flush:
            session.flush()

    def update(self, values, flush=True, session=None):
        """dict.update() behaviour."""
        for k, v in values.items():
            self[k] = v
        if session and flush:
            session.flush()

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def __getitem__(self, key):
        return getattr(self, key)

    def __iter__(self):
        self._i = iter(object_mapper(self).columns)
        return self

    def __next__(self):
        n = next(self._i).name
        return n, getattr(self, n)

    def keys(self):
        return list(self.__dict__.keys())

    def values(self):
        return list(self.__dict__.values())

    def items(self):
        return list(self.__dict__.items())

    def to_dict(self):
        dictionary = self.__dict__.copy()
        dictionary.pop("_sa_instance_state")
        return dictionary

    next = __next__


class SoftModelBase(ModelBase):
    """Base class for Models with soft-deletion support"""

    __table_initialized__ = False

    @declared_attr
    def __table_args__(cls):
        return cls._table_args + (
            CheckConstraint("CREATED_AT IS NOT NULL", name=cls.__tablename__.upper() + "_CREATED_NN"),
            CheckConstraint("UPDATED_AT IS NOT NULL", name=cls.__tablename__.upper() + "_UPDATED_NN"),
            CheckConstraint("DELETED IS NOT NULL", name=cls.__tablename__.upper() + "_DELETED_NN"),
            {"mysql_engine": "InnoDB", "info": {"soft_delete": True}},
        )

    def delete(self, flush=True, session=None):
        """Delete this object"""
        self.deleted = True
        self.deleted_at = datetime.datetime.utcnow()
        self.save(session=session)


class SystemSetting(BASE, ModelBase):
    """Represents a quantum node attributes"""

    __tablename__ = "system_setting"
    id = Column(GUID(), default=utils.generate_uuid)

    type = Column(String(255))
    name = Column(String(255))
    ID = Column(String(255))
    controlInterface = Column(String(255))
    mode = Column(String(255))
    threads = Column(BigInteger)
    workers = Column(BigInteger)

    qnode_id = Column(GUID())
    bsmnode_id = Column(GUID())
    mnode_id = Column(GUID())
    switch_id = Column(GUID())

    qnode = relationship('Qnode', back_populates='system_settings')
    bsmnode = relationship('BSMnode', back_populates='system_settings')
    mnode = relationship('Mnode', back_populates='system_settings')
    switch = relationship('Switch', back_populates='system_settings')

    _table_args = (PrimaryKeyConstraint('id', 'type', name='SYSTEM_SETTING_PK'),
                   ForeignKeyConstraint(['qnode_id'], ['qnodes.id'], name='SYSTEM_SETTING_MAP_QNODE_FK'),
                   ForeignKeyConstraint(['bsmnode_id'], ['bsmnodes.id'], name='SYSTEM_SETTING_MAP_BSMNODE_FK'),
                   ForeignKeyConstraint(['mnode_id'], ['mnodes.id'], name='SYSTEM_SETTING_MAP_MNODE_FK'),
                   ForeignKeyConstraint(['switch_id'], ['switches.id'], name='SYSTEM_SETTING_MAP_SWITCH_FK'))


class QuantumSetting(BASE, ModelBase):
    """ Represents a quantum setting """
    __tablename__ = 'quantum_setting'
    id = Column(GUID(), default=utils.generate_uuid)

    """ bsm node """
    bellStates = Column(ARRAY(String(255)))
    measurementRate = Column(BigInteger)
    qubitEncoding = Column(String(255))
    detectorSettings = relationship('Detector', back_populates='quantum_setting')
    bsmnode_id = Column(GUID())
    bsmnode = relationship('BSMnode', back_populates='quantum_settings')

    """ mnode """
    defaultMeasurementBase = Column(CHAR)
    advancedBase = Column(Float)
    flyingQubit = Column(Sqla_JSON)
    wavelength = Column(Sqla_JSON)
    tomographyAnalysis = Column(Boolean)
    maxMeasurementRate = Column(BigInteger)

    mnode_id = Column(GUID())
    mnode = relationship('Mnode', back_populates='quantum_settings')

    _table_args = (PrimaryKeyConstraint('id', name='QUANTUM_ID_PK'),
                   ForeignKeyConstraint(['bsmnode_id'], ['bsmnodes.id'], name='BSMNODE_ID_FK'),
                   ForeignKeyConstraint(['mnode_id'], ['mnodes.id'], name='MNODE_ID_FK'))


class QubitSetting(BASE, ModelBase):
    """Represents a quantum node attributes"""

    __tablename__ = "qubit_setting"
    id = Column(GUID(), default=utils.generate_uuid)

    qbits = relationship("Qbit", back_populates="qubit_setting")
    operations = relationship("QbitGate", back_populates="qubit_setting")

    qnode_id = Column(GUID())
    qnode = relationship('Qnode', back_populates='qubit_settings')

    _table_args = (
        PrimaryKeyConstraint("id", name="QUBIT_SETTING_PK"),
        ForeignKeyConstraint(["qnode_id"], ["qnodes.id"], name="QUBIT_SETTING_MAP_QNODE_FK"),
    )


class MatterLightInterfaceSetting(BASE, ModelBase):
    """Represents a light interface attributes"""

    __tablename__ = "matterlightinterface_setting"
    id = Column(GUID(), default=utils.generate_uuid)

    ID = Column(String(255))
    name = Column(String(255))
    interface = Column(String(255))
    entanglement = Column(Sqla_JSON)
    flyingQubit = Column(Sqla_JSON)

    qnode_id = Column(GUID())
    qnode = relationship('Qnode', back_populates='matterlightinterface_settings')

    _table_args = (
        PrimaryKeyConstraint("id", name="INTERFACE_SETTING_PK"),
        ForeignKeyConstraint(["qnode_id"], ["qnodes.id"], name="MATTERLIGHTINTERFACE_SETTING_MAP_QNODE_FK"),
    )


class Qbit(BASE, ModelBase):
    """Represents a qbit setting"""

    __tablename__ = "qbit"
    id = Column(GUID(), default=utils.generate_uuid)
    qbitsetting_id = Column(GUID())

    ID = Column(String(255))
    quantumObject = Column(String(255))
    T1 = Column(Sqla_JSON)
    T2 = Column(Sqla_JSON)
    type = Column(String(255))

    qubit_setting = relationship("QubitSetting", back_populates="qbits")

    _table_args = (
        PrimaryKeyConstraint("id", name="QBIT_PK"),
        ForeignKeyConstraint(["qbitsetting_id"], ["qubit_setting.id"], name="QBITSETTING_ID_FK"),
    )


class QbitGate(BASE, ModelBase):
    """Represents a qbit gate"""

    __tablename__ = "qbitgate"
    id = Column(GUID(), default=utils.generate_uuid)
    qbitsetting_id = Column(GUID())

    gate = Column(String(255))
    qubits = Column(ARRAY(String(255)))
    type = Column(String(255))

    qubit_setting = relationship("QubitSetting", back_populates="operations")

    _table_args = (
        PrimaryKeyConstraint("id", "gate", name="QBIT_GATE_PK"),
        # ForeignKeyConstraint(['qnode_id'], ['qnodes.id'], name='QNODE_ID_FK'),
        ForeignKeyConstraint(["qbitsetting_id"], ["qubit_setting.id"], name="QUBITSETTING_ID_FK"),
    )


class Neighbor(BASE, ModelBase):
    """Represents a neighbor"""

    __tablename__ = "neighbor"
    id = Column(GUID(), default=utils.generate_uuid)

    idRef = Column(String(255))
    systemRef = Column(String(255))
    channelRef = Column(String(255))
    type = Column(String(255))
    loss = Column(Sqla_JSON)

    channel_id = Column(GUID())

    channel = relationship("Channel", back_populates="neighbor")

    _table_args = (PrimaryKeyConstraint('id', name='NEIGHBOR_ID_PK'),
                   ForeignKeyConstraint(['channel_id'], ['channel.id'], name='CHANNEL_ID_FK'))


class Channel(BASE, ModelBase):
    """Represents a channel"""

    __tablename__ = "channel"
    id = Column(GUID(), default=utils.generate_uuid)

    ID = Column(String(255))
    name = Column(String(255))
    type = Column(String(255))
    direction = Column(String(255))
    wavelength = Column(Sqla_JSON)
    power = Column(Float)
    length = Column(Sqla_JSON)
    neighbor = relationship('Neighbor', back_populates='channel')

    qnode_id = Column(GUID())
    bsmnode_id = Column(GUID())
    mnode_id = Column(GUID())
    switch_id = Column(GUID())

    qnode = relationship('Qnode', back_populates='channels')
    bsmnode = relationship('BSMnode', back_populates='channels')
    mnode = relationship('Mnode', back_populates='channels')
    switch = relationship('Switch', back_populates='channels')

    _table_args = (PrimaryKeyConstraint('id', name='CHANNEL_ID_PK'),
                   ForeignKeyConstraint(['qnode_id'], ['qnodes.id'], name='QNODE_ID_FK'),
                   ForeignKeyConstraint(['bsmnode_id'], ['bsmnodes.id'], name='BSMNODE_ID_FK'),
                   ForeignKeyConstraint(['mnode_id'], ['mnodes.id'], name='MNODE_ID_FK'),
                   ForeignKeyConstraint(['switch_id'], ['switches.id'], name='SWITCH_ID_FK')
                   )


class Detector(BASE, ModelBase):
    """ Represents a detector """
    __tablename__ = 'detector'
    id = Column(GUID(), default=utils.generate_uuid)

    name = Column(String(255))
    efficiency = Column(String(255))
    darkCount = Column(String(255))
    countRate = Column(Sqla_JSON)
    timeResolution = Column(Sqla_JSON)

    quantum_setting_id = Column(GUID())
    quantum_setting = relationship('QuantumSetting', back_populates='detectorSettings')

    _table_args = (PrimaryKeyConstraint('id', name='DETECTOR_ID_PK'),
                   ForeignKeyConstraint(['quantum_setting_id'], ['quantum_setting.id'], name='QUANTUME_SETTING_ID_FK'))


class Qnode(BASE, ModelBase):
    """Represents a quantum node"""
    __tablename__ = 'qnodes'
    id = Column(GUID(), default=utils.generate_uuid)

    status = Column(Enum(NodeStatus, name='QNODES_STATUS_CHK',
                         create_constraint=True,
                         values_callable=lambda obj: [e.value for e in obj]),
                    default=NodeStatus.ACTIVE, )
    suspended_at = Column(DateTime)
    deleted_at = Column(DateTime)

    system_settings = relationship('SystemSetting', back_populates='qnode')
    qubit_settings = relationship('QubitSetting', back_populates='qnode')
    matterlightinterface_settings = relationship('MatterLightInterfaceSetting', back_populates='qnode')
    channels = relationship('Channel', back_populates='qnode')

    _table_args = (PrimaryKeyConstraint('id', name='QNODES_PK'),
                   CheckConstraint('STATUS IS NOT NULL', name='QNODES_STATUS_NN'))


class Switch(BASE, ModelBase):
    """Represents a optical switch node"""
    __tablename__ = 'switches'
    id = Column(GUID(), default=utils.generate_uuid)

    status = Column(Enum(NodeStatus, name='SWITCH_STATUS_CHK',
                         create_constraint=True,
                         values_callable=lambda obj: [e.value for e in obj]),
                    default=NodeStatus.ACTIVE, )
    suspended_at = Column(DateTime)
    deleted_at = Column(DateTime)

    system_settings = relationship('SystemSetting', back_populates='switch')
    channels = relationship('Channel', back_populates='switch')

    _table_args = (PrimaryKeyConstraint('id', name='SWITCH_PK'),
                   CheckConstraint('STATUS IS NOT NULL', name='SWITCH_STATUS_NN'))


class BSMnode(BASE, ModelBase):
    """Represents a BSM node"""
    __tablename__ = 'bsmnodes'
    id = Column(GUID(), default=utils.generate_uuid)

    status = Column(Enum(NodeStatus, name='SWITCH_STATUS_CHK',
                         create_constraint=True,
                         values_callable=lambda obj: [e.value for e in obj]),
                    default=NodeStatus.ACTIVE, )
    suspended_at = Column(DateTime)
    deleted_at = Column(DateTime)

    system_settings = relationship('SystemSetting', back_populates='bsmnode')
    quantum_settings = relationship('QuantumSetting', back_populates='bsmnode')
    channels = relationship('Channel', back_populates='bsmnode')

    _table_args = (PrimaryKeyConstraint('id', name='BSMNODE_PK'),
                   CheckConstraint('STATUS IS NOT NULL', name='BSMNODE_STATUS_NN'))


class Mnode(BASE, ModelBase):
    """Represents a M node"""
    __tablename__ = 'mnodes'
    id = Column(GUID(), default=utils.generate_uuid)

    status = Column(Enum(NodeStatus, name='SWITCH_STATUS_CHK',
                         create_constraint=True,
                         values_callable=lambda obj: [e.value for e in obj]),
                    default=NodeStatus.ACTIVE, )
    suspended_at = Column(DateTime)
    deleted_at = Column(DateTime)

    system_settings = relationship('SystemSetting', back_populates='mnode')
    # measurement_settings = relationship('MeasurementSetting', back_populates='mnode')
    quantum_settings = relationship('QuantumSetting', back_populates='mnode')
    channels = relationship('Channel', back_populates='mnode')

    _table_args = (PrimaryKeyConstraint('id', name='MNODE_PK'),
                   CheckConstraint('STATUS IS NOT NULL', name='MNODE_STATUS_NN'))


class Calibration(BASE, ModelBase):
    """Represents a calibration operation"""
    __tablename__ = 'calibrations'
    id = Column(GUID(), default=utils.generate_uuid)

    status = Column(Enum(NodeStatus, name='CALIBRATION_STATUS_CHK',
                         create_constraint=True,
                         values_callable=lambda obj: [e.value for e in obj]),
                    default=NodeStatus.ACTIVE, )
    suspended_at = Column(DateTime)
    deleted_at = Column(DateTime)

    src = Column(String(255))
    dst = Column(String(255))
    power = Column(Float)
    light = Column(String(1))
    phase = Column(String(16))

    _table_args = (PrimaryKeyConstraint('id', name='CALIBRATION_PK'),
                   CheckConstraint('STATUS IS NOT NULL', name='CALIBRATION_STATUS_NN'))


class PingPong(BASE, ModelBase):
    """Represents a pinpong operation"""
    __tablename__ = 'pingpongs'
    id = Column(GUID(), default=utils.generate_uuid)

    status = Column(Enum(NodeStatus, name='PINGPONG_STATUS_CHK',
                         create_constraint=True,
                         values_callable=lambda obj: [e.value for e in obj]),
                    default=NodeStatus.ACTIVE, )
    suspended_at = Column(DateTime)
    deleted_at = Column(DateTime)

    remote = Column(String(255))
    reason = Column(String(255))
    iterations = Column(BigInteger)
    phase = Column(String(16))

    _table_args = (PrimaryKeyConstraint('id', name='PINGPONG_PK'),
                   CheckConstraint('STATUS IS NOT NULL', name='PINGPONG_STATUS_NN'))


class Blob(BASE, ModelBase):
    """Represents a blbo operation"""
    __tablename__ = 'blob'
    id = Column(GUID(), default=utils.generate_uuid)

    status = Column(Enum(NodeStatus, name='BLOB_STATUS_CHK',
                         create_constraint=True,
                         values_callable=lambda obj: [e.value for e in obj]),
                    default=NodeStatus.ACTIVE, )
    suspended_at = Column(DateTime)
    deleted_at = Column(DateTime)

    data = Column(LargeBinary)

    _table_args = (PrimaryKeyConstraint('id', name='BLOB_PK'),
                   CheckConstraint('STATUS IS NOT NULL', name='BLOB_STATUS_NN'))


def register_models(engine):
    """
    Creates database tables for all models with the given engine
    """
    models = (Qnode,
              Switch,
              BSMnode,
              Mnode,
              SystemSetting,
              QuantumSetting,
              QubitSetting,
              Qbit,
              Channel,
              Blob)

    for model in models:
        model.metadata.create_all(engine)


def unregister_models(engine):
    """
    Drops database tables for all models with the given engine
    """
    models = (Qnode,
              BSMnode,
              Mnode,
              Switch,
              SystemSetting,
              QuantumSetting,
              QubitSetting,
              Qbit,
              Channel,
              Blob)

    for model in models:
        model.metadata.drop_all(engine)
