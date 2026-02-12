from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import exc

from quantnet_controller.common import exception
from quantnet_controller.common.utils import generate_uuid
from quantnet_controller.db.sqla import models
from quantnet_controller.db.sqla.constants import NodeStatus, NodeType
from quantnet_controller.db.sqla.session import read_session, transactional_session

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@transactional_session
def add_bsmnode(id, system_settings=None, quantum_settings=None, channels=None, *, session: "Session"):
    """ Add an bsmnode with the given id, name and type.

    :param id: the name of the new bsmnode.
    :param name: the name of the new bsmnode.
    :param type_: the type of the new bsmnode.
    :param email: The Email address associated with the bsmnode.
    :param session: the database session in use.
    """

    if channels:
        cs = []
        for ch in channels:
            cch = {k: v for k, v in ch.items() if k != 'neighbor'}
            n = models.Neighbor(**ch['neighbor'])
            c = models.Channel(**cch, neighbor=[n])
            cs.append(c)
        new_bsmnode = models.BSMnode(id=id, status=NodeStatus.ACTIVE, channels=cs)
    else:
        new_bsmnode = models.BSMnode(id=id, status=NodeStatus.ACTIVE)

    if system_settings:
        ss = models.SystemSetting(bsmnode_id=id, **system_settings)
        new_bsmnode.system_settings.append(ss)

    if quantum_settings:
        qs_id = generate_uuid()
        ds = []
        for detector in quantum_settings['detectorSettings']:
            d = models.Detector(quantum_setting_id=qs_id, **detector)
            ds.append(d)

        qs = models.QuantumSetting(
            bsmnode_id=id,
            bellStates=quantum_settings['bellStates'],
            measurementRate=quantum_settings['measurementRate'],
            qubitEncoding=quantum_settings['qubitEncoding'],
            detectorSettings=ds)

        new_bsmnode.quantum_settings.append(qs)

    try:
        new_bsmnode.save(session=session)
    except IntegrityError:
        raise exception.Duplicate('BSMnode ID \'%s\' already exists!' % id)


@read_session
def bsmnode_exists(id, *, session: "Session"):
    """ Checks to see if bsmnode exists.

    :param id: ID of the bsmnode.
    :param session: the database session in use.

    :returns: True if found, otherwise false.
    """

    query = session.query(models.BSMnode).filter_by(id=id, status=NodeStatus.ACTIVE)

    return True if query.first() else False


@read_session
def get_bsmnode(id, *, session: "Session"):
    """ Returns an bsmnode for the given id.

    :param id: the id of the bsmnode.
    :param session: the database session in use.

    :returns: a dict with all information for the bsmnode.
    """

    query = session.query(models.BSMnode).filter_by(id=id)

    try:
        result = query.one()
    except exc.NoResultFound:
        raise exception.NodeNotFound('BSMnode with ID \'%s\' cannot be found' % id)

    bsmnode = {}

    if result.system_settings:
        keys = ('type', 'name', 'ID', 'controlInterface', 'queue', 'mode', 'threads', 'workers')
        sys_setting = {k: v for k, v in result.system_settings[0].__dict__.items() if k in keys}
        bsmnode.update({'systemSettings': sys_setting})

    if result.quantum_settings:
        quantum_setting = {}
        quantum_setting.update({'bellStates': result.quantum_settings[0].bellStates})
        quantum_setting.update({'measurementRate': result.quantum_settings[0].measurementRate})
        quantum_setting.update({'qubitEncoding': result.quantum_settings[0].qubitEncoding})

        detectorSettings = []
        for detector in result.quantum_settings[0].detectorSettings:
            detector_dict = {}
            keys = ('name', 'efficiency', 'darkCount', 'countRate', 'timeResolution')
            detector_dict = {k: v for k, v in detector.__dict__.items() if k in keys}
            detectorSettings.append(detector_dict)
        quantum_setting.update({'detectorSettings': detectorSettings})

        bsmnode.update({'quantumSettings': quantum_setting})

    if result.channels:
        channels = []
        channel_keys = ('ID', 'name', 'type', 'direction', 'wavelength', 'power', 'length', 'neighbor')
        neighbor_keys = ('idRef', 'systemRef', 'channelRef', 'loss', 'type')

        for ch in result.channels:
            channel = {k: v for k, v in ch.__dict__.items() if k in channel_keys}
            neighbor = {k: v for k, v in ch.neighbor[0].__dict__.items() if k in neighbor_keys}
            channel.update({'neighbor': neighbor})
            channels.append(channel)

        bsmnode.update({'channels': channels})

    return bsmnode


@transactional_session
def del_bsmnode(id, *, session: "Session"):
    """ Disable a bsmnode with the given id.

    :param id: the bsmnode id.
    :param session: the database session in use.
    """
    query = session.query(models.BSMnode).filter_by(id=id).filter_by(status=NodeStatus.ACTIVE)
    try:
        bsmnode = query.one()
    except exc.NoResultFound:
        raise exception.NodeNotFound('bsmnode with ID \'%s\' cannot be found' % id)

    bsmnode.update({'status': NodeStatus.DELETED, 'deleted_at': datetime.utcnow()})


@transactional_session
def update_bsmnode(id, key, value, *, session: "Session"):
    """ Update a property of an bsmnode.

    :param id: ID of the bsmnode.
    :param key: bsmnode property like status.
    :param value: Property value.
    :param session: the database session in use.
    """
    query = session.query(models.BSMnode).filter_by(id=id)
    try:
        bsmnode = query.one()
    except exc.NoResultFound:
        raise exception.NodeNotFound('BSMnode with ID \'%s\' cannot be found' % id)
    if key == 'status':
        if isinstance(value, str):
            value = NodeStatus[value]
        if value == NodeStatus.SUSPENDED:
            bsmnode.update({'status': value, 'suspended_at': datetime.utcnow()})
        elif value == NodeStatus.ACTIVE:
            bsmnode.update({'status': value, 'suspended_at': None})
    else:
        bsmnode.update({key: value})

@read_session
def list_bsmnodes(filter_=None, *, session: "Session"):
    """ Returns a list of all bsmnode names.

    :param filter_: Dictionary of attributes by which the input data should be filtered
    :param session: the database session in use.

    returns: a list of all bsmnode names.
    """
    if filter_ is None:
        filter_ = {}
    query = session.query(models.BSMnode).filter_by(status=NodeStatus.ACTIVE)
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
                query = query.filter_by(id=filter_['id'])
        else:
            query = query.join(models.QNodeAttr, models.Qnode.id == models.QNodeAttr.qnode_id).\
                filter(models.QNodeAttr.key == filter_type).\
                filter(models.QNodeAttr.value == filter_[filter_type])

    bsmnode_list = []
    for row in query:
        bsmnode = get_bsmnode(row.id)
        bsmnode_list.append(bsmnode)

    return bsmnode_list
