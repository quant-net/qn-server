from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import exc

# from quantnet_controller.common import exception
from quantnet_controller.common.utils import generate_uuid
from quantnet_controller.db.sqla import models
from quantnet_controller.db.sqla.constants import NodeStatus, NodeType
from quantnet_controller.db.sqla.session import read_session, transactional_session
from quantnet_controller.common.exception import NodeNotFound, Duplicate

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@transactional_session
def add_qnode(id,
              system_settings=None,
              qubit_settings=None,
              interface_settings=None,
              channel_settings=None,
              *,
              session: "Session"):
    """Add an qnode with the given id, name and type.

    :param id: the name of the new qnode.
    :param name: the name of the new qnode.
    :param type_: the type of the new qnode.
    :param email: The Email address associated with the qnode.
    :param session: the database session in use.
    """

    new_qnode = models.Qnode(id=id, status=NodeStatus.ACTIVE)
    if system_settings:
        ss = models.SystemSetting(qnode_id=id, **system_settings)
        new_qnode.system_settings.append(ss)

    if qubit_settings:
        qs_id = generate_uuid()
        qs = models.QubitSetting(id=qs_id, qnode_id=id)

        for qubit in qubit_settings["qubits"]:
            q = models.Qbit(qbitsetting_id=qs_id, **qubit)
            qs.qbits.append(q)

        for op_type, ops in qubit_settings["operations"].items():
            for gate in ops:
                op = models.QbitGate(qbitsetting_id=qs_id, **gate, type=op_type)
                qs.operations.append(op)

        new_qnode.qubit_settings.append(qs)

    if interface_settings:
        for interface_setting in interface_settings:
            ffs = {k: v for k, v in interface_setting.items() if k != "channels"}
            fs = models.MatterLightInterfaceSetting(qnode_id=id, **ffs)

            new_qnode.matterlightinterface_settings.append(fs)

    if channel_settings:
        for ch in channel_settings:
            cch = {k: v for k, v in ch.items() if k != "neighbor"}
            n = models.Neighbor(**ch["neighbor"])
            c = models.Channel(qnode_id=id, **cch, neighbor=[n])
            new_qnode.channels.append(c)

    try:
        new_qnode.save(session=session)
    except IntegrityError:
        raise Duplicate(f"Qnode ID '{id}' already exists!")


@read_session
def qnode_exists(id, *, session: "Session"):
    """Checks to see if qnode exists.

    :param id: ID of the qnode.
    :param session: the database session in use.

    :returns: True if found, otherwise false.
    """

    query = session.query(models.Qnode).filter_by(id=id, status=NodeStatus.ACTIVE)

    return True if query.first() else False


@read_session
def get_qnode(id, *, session: "Session"):
    """Returns an qnode for the given id.

    :param id: the id of the qnode.
    :param session: the database session in use.

    :returns: a dict with all information for the qnode.
    """

    query = session.query(models.Qnode).filter_by(id=id)

    try:
        result = query.one()
    except exc.NoResultFound:
        raise NodeNotFound(f"Qnode with ID '{id}' cannot be found")

    qnode = {}

    if result.system_settings:
        keys = ("type", "name", "ID", "controlInterface", "queue", "mode", "threads", "workers")
        sys_setting = {k: v for k, v in result.system_settings[0].__dict__.items() if k in keys}
        qnode.update({"systemSettings": sys_setting})

    if result.qubit_settings:
        qbit_setting = {}
        qubits_dict = []
        for qubit in result.qubit_settings[0].qbits:
            qubit_dict = {}
            keys = ("ID", "quantumObject", "T1", "T2", "type")
            qubit_dict = {k: v for k, v in qubit.__dict__.items() if k in keys}
            qubits_dict.append(qubit_dict)

        oneQubit = []
        twoQubit = []
        for operation in result.qubit_settings[0].operations:
            keys = ("gate", "qubits", "type")
            qbitgate = {k: v for k, v in operation.__dict__.items() if k in keys}

            if qbitgate["type"] == "oneQubitGates":
                qbitgate.pop("type")
                oneQubit.append(qbitgate)
            elif qbitgate["type"] == "twoQubitGates":
                qbitgate.pop("type")
                twoQubit.append(qbitgate)
            else:
                raise NodeNotFound(f"Qnode with ID '{id}' has unknown type {qbitgate['type']}")

        qbit_setting.update({"qubits": qubits_dict})
        qbit_setting.update({"operations": {"oneQubitGates": oneQubit, "twoQubitGates": twoQubit}})
        qnode.update({"qubitSettings": qbit_setting})

    if result.matterlightinterface_settings:
        output_keys = ("ID", "name", "entanglement", "flyingQubit")
        interface_settings = []
        for intf_setting in result.matterlightinterface_settings:
            intf_dict = {k: v for k, v in intf_setting.__dict__.items() if k in output_keys}
            interface_settings.append(intf_dict)
        qnode.update({"matterLightInterfaceSettings": interface_settings})

    if result.channels:
        channels = []
        channel_keys = ('ID', 'name', 'type', 'direction', 'wavelength', 'power', 'length', 'neighbor')
        for ch in result.channels:
            channel = {k: v for k, v in ch.__dict__.items() if k in channel_keys}
            neighbor_keys = ('idRef', 'systemRef', 'channelRef', 'loss', 'type')
            neighbor = {k: v for k, v in ch.neighbor[0].__dict__.items() if k in neighbor_keys}
            channel.update({'neighbor': neighbor})
            channels.append(channel)
        qnode.update({"channels": channels})

    return qnode


@transactional_session
def del_qnode(id, *, session: "Session"):
    """Disable a qnode with the given id.

    :param id: the qnode id.
    :param session: the database session in use.
    """
    query = session.query(models.Qnode).filter_by(id=id).filter_by(status=NodeStatus.ACTIVE)
    try:
        qnode = query.one()
    except exc.NoResultFound:
        raise NodeNotFound(f"qnode with ID '{id}' cannot be found")

    qnode.update({"status": NodeStatus.DELETED, "deleted_at": datetime.utcnow()})


@transactional_session
def update_qnode(id, key, value, *, session: "Session"):
    """Update a property of an qnode.

    :param id: ID of the qnode.
    :param key: Qnode property like status.
    :param value: Property value.
    :param session: the database session in use.
    """
    query = session.query(models.Qnode).filter_by(id=id)
    try:
        qnode = query.one()
        qnode
    except exc.NoResultFound:
        raise NodeNotFound(f"Qnode with ID '{id}' cannot be found")
    if key == "status":
        if isinstance(value, str):
            value = NodeStatus[value]
        if value == NodeStatus.SUSPENDED:
            query.update({"status": value, "suspended_at": datetime.utcnow()})
        elif value == NodeStatus.ACTIVE:
            query.update({"status": value, "suspended_at": None})
    else:
        query.update({key: value})

@read_session
def list_qnodes(filter_=None, *, session: "Session"):
    """Returns a list of all qnode names.

    :param filter_: Dictionary of attributes by which the input data should be filtered
    :param session: the database session in use.

    returns: a list of all qnode names.
    """
    if filter_ is None:
        filter_ = {}
    query = session.query(models.Qnode).filter_by(status=NodeStatus.ACTIVE)
    for filter_type in filter_:
        if filter_type == 'qnode_type':
            if isinstance(filter_['qnode_type'], str):
                query = query.filter_by(qnode_type=NodeType[filter_['qnode_type']])
            elif isinstance(filter_['qnode_type'], Enum):
                query = query.filter_by(qnode_type=filter_['qnode_type'])

        elif filter_type == 'id':
            if '*' in filter_['id'].internal:
                account_str = filter_['id'].internal.replace('*', '%')
                query = query.filter(models.Qnode.id.like(account_str))
            else:
                query = query.filter_by(id=filter_["id"])
        else:
            query = query.join(models.QNodeAttr, models.Qnode.id == models.QNodeAttr.qnode_id).\
                filter(models.QNodeAttr.key == filter_type).\
                filter(models.QNodeAttr.value == filter_[filter_type])

    qnode_list = []
    for row in query:
        qnode = get_qnode(row.id)
        qnode_list.append(qnode)

    return qnode_list
