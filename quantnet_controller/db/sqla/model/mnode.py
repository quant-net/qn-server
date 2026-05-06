from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import exc

from quantnet_controller.common import exception
from quantnet_controller.common.utils import generate_uuid
from quantnet_controller.db.sqla import models
from quantnet_controller.db.sqla.constants import NodeStatus, NodeType
from quantnet_controller.db.sqla.session import read_session, transactional_session  # , stream_session

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@transactional_session
def add_mnode(id, system_settings=None, quantum_settings=None, channels=None, *, session: "Session"):
    """ Add an mnode with the given id, name and type.

    :param id: the name of the new mnode.
    :param name: the name of the new mnode.
    :param type_: the type of the new mnode.
    :param email: The Email address associated with the mnode.
    :param session: the database session in use.
    """

    new_mnode = models.Mnode(id=id, status=NodeStatus.ACTIVE)

    if channels:
        cs = []
        for ch in channels:
            cch = {k: v for k, v in ch.items() if k != 'neighbor'}
            n = models.Neighbor(**ch['neighbor'])
            c = models.Channel(**cch, neighbor=[n])
            cs.append(c)
        new_mnode = models.Mnode(id=id, status=NodeStatus.ACTIVE, channels=cs)
    else:
        new_mnode = models.Mnode(id=id, status=NodeStatus.ACTIVE)

    if system_settings:
        ss = models.SystemSetting(mnode_id=id, **system_settings)
        new_mnode.system_settings.append(ss)

    if quantum_settings:
        qs_id = generate_uuid()
        ds = []
        for detector in quantum_settings['detectorSettings']:
            d = models.Detector(quantum_setting_id=qs_id, **detector)
            ds.append(d)

        nodetector = {k: v for k, v in quantum_settings.items() if k not in {"detectorSettings"}}
        qs = models.QuantumSetting(
            mnode_id=id,
            **nodetector,
            detectorSettings=ds)

        new_mnode.quantum_settings.append(qs)

    try:
        new_mnode.save(session=session)
    except IntegrityError:
        raise exception.Duplicate('Mnode ID \'%s\' already exists!' % id)


@read_session
def mnode_exists(id, *, session: "Session"):
    """ Checks to see if mnode exists.

    :param id: ID of the mnode.
    :param session: the database session in use.

    :returns: True if found, otherwise false.
    """

    query = session.query(models.Mnode).filter_by(id=id, status=NodeStatus.ACTIVE)

    return True if query.first() else False


@read_session
def get_mnode(id, *, session: "Session"):
    """ Returns an mnode for the given id.

    :param id: the id of the mnode.
    :param session: the database session in use.

    :returns: a dict with all information for the mnode.
    """

    query = session.query(models.Mnode).filter_by(id=id)

    try:
        result = query.one()
    except exc.NoResultFound:
        raise exception.NodeNotFound('Mnode with ID \'%s\' cannot be found' % id)

    # TODO: complete with mnode data fields
    mnode = {}

    if result.system_settings:
        keys = ('type', 'name', 'ID', 'controlInterface', 'queue', 'mode', 'threads', 'workers')
        sys_setting = {k: v for k, v in result.system_settings[0].__dict__.items() if k in keys}
        mnode.update({'systemSettings': sys_setting})

    if result.quantum_settings:
        quantum_setting = {}
        quantum_setting.update({'defaultMeasurementBase': result.quantum_settings[0].defaultMeasurementBase})
        quantum_setting.update({'advancedBase': result.quantum_settings[0].advancedBase})
        quantum_setting.update({'flyingQubit': result.quantum_settings[0].flyingQubit})
        quantum_setting.update({'wavelength': result.quantum_settings[0].wavelength})
        quantum_setting.update({'tomographyAnalysis': result.quantum_settings[0].tomographyAnalysis})
        quantum_setting.update({'maxMeasurementRate': result.quantum_settings[0].maxMeasurementRate})

        detectorSettings = []
        for detector in result.quantum_settings[0].detectorSettings:
            detector_dict = {}
            keys = ('name', 'efficiency', 'darkCount', 'countRate', 'timeResolution')
            detector_dict = {k: v for k, v in detector.__dict__.items() if k in keys}
            detectorSettings.append(detector_dict)
        quantum_setting.update({'detectorSettings': detectorSettings})

        mnode.update({'quantumSettings': quantum_setting})

    if result.channels:
        channels = []
        channel_keys = ('ID', 'name', 'type', 'direction', 'wavelength', 'power', 'length', 'neighbor')
        neighbor_keys = ('idRef', 'systemRef', 'channelRef', 'loss', 'type')

        for ch in result.channels:
            channel = {k: v for k, v in ch.__dict__.items() if k in channel_keys}
            neighbor = {k: v for k, v in ch.neighbor[0].__dict__.items() if k in neighbor_keys}
            channel.update({'neighbor': neighbor})
            channels.append(channel)

        mnode.update({'channels': channels})

    return mnode


@transactional_session
def del_mnode(id, *, session: "Session"):
    """ Disable a mnode with the given id.

    :param id: the mnode id.
    :param session: the database session in use.
    """
    query = session.query(models.Mnode).filter_by(id=id).filter_by(status=NodeStatus.ACTIVE)
    try:
        mnode = query.one()
    except exc.NoResultFound:
        raise exception.NodeNotFound('mnode with ID \'%s\' cannot be found' % id)

    mnode.update({'status': NodeStatus.DELETED, 'deleted_at': datetime.utcnow()})


@transactional_session
def update_mnode(id, key, value, *, session: "Session"):
    """ Update a property of an mnode.

    :param id: ID of the mnode.
    :param key: mnode property like status.
    :param value: Property value.
    :param session: the database session in use.
    """
    query = session.query(models.Mnode).filter_by(id=id)
    try:
        mnode = query.one()
    except exc.NoResultFound:
        raise exception.NodeNotFound('Mnode with ID \'%s\' cannot be found' % id)
    if key == 'status':
        if isinstance(value, str):
            value = NodeStatus[value]
        if value == NodeStatus.SUSPENDED:
            mnode.update({'status': value, 'suspended_at': datetime.utcnow()})
        elif value == NodeStatus.ACTIVE:
            mnode.update({'status': value, 'suspended_at': None})
    else:
        mnode.update({key: value})

@read_session
def list_mnodes(filter_=None, *, session: "Session"):
    """ Returns a list of all mnode names.

    :param filter_: Dictionary of attributes by which the input data should be filtered
    :param session: the database session in use.

    returns: a list of all mnode names.
    """
    if filter_ is None:
        filter_ = {}
    query = session.query(models.Mnode).filter_by(status=NodeStatus.ACTIVE)
    for filter_type in filter_:
        if filter_type == 'mnode_type':
            if isinstance(filter_['mnode_type'], str):
                query = query.filter_by(mnode_type=NodeType[filter_['mnode_type']])
            elif isinstance(filter_['mnode_type'], Enum):
                query = query.filter_by(mnode_type=filter_['mnode_type'])

        elif filter_type == 'id':
            if '*' in filter_['id'].internal:
                account_str = filter_['id'].internal.replace('*', '%')
                query = query.filter(models.Mnode.id.like(account_str))
            else:
                query = query.filter_by(id=filter_['id'])
        else:
            query = query.join(models.MNodeAttr, models.Mnode.id == models.MNodeAttr.qnode_id).\
                filter(models.MNodeAttr.key == filter_type).\
                filter(models.MNodeAttr.value == filter_[filter_type])

    mnode_list = []
    for row in query:
        mnode = get_mnode(row.id)
        mnode_list.append(mnode)

    return mnode_list
