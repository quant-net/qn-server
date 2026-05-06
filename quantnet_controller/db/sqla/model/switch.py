from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import exc

from quantnet_controller.common import exception
from quantnet_controller.db.sqla import models
from quantnet_controller.db.sqla.constants import NodeStatus, NodeType
from quantnet_controller.db.sqla.session import read_session, transactional_session

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@transactional_session
def add_switch(id, system_settings=None, channels=None, *, session: "Session"):
    """ Add an switch with the given id, name and type.

    :param id: the name of the new switch.
    :param name: the name of the new switch.
    :param type_: the type of the new switch.
    :param email: The Email address associated with the switch.
    :param session: the database session in use.
    """

    try:
        new_node = models.Switch(id=id, status=NodeStatus.ACTIVE)
    except Exception as e:
        raise e
    if system_settings:
        ss = models.SystemSetting(switch_id=id, **system_settings)
        new_node.system_settings.append(ss)

    if channels:
        for ch in channels:
            cch = {k: v for k, v in ch.items() if k != 'neighbor'}
            n = models.Neighbor(**ch['neighbor'])
            # c.neighbor.append({'neighbor': n})
            c = models.Channel(switch_id=id, **cch, neighbor=[n])
            new_node.channels.append(c)

    try:
        new_node.save(session=session)
    except IntegrityError:
        raise exception.Duplicate(f'Switch ID {id} already exists!')
    except OperationalError as e:
        raise exception.DatabaseException(e.args)
    except Exception as e:
        raise e


@read_session
def switch_exists(id, *, session: "Session"):
    """ Checks to see if a switch exists.

    :param id: ID of the switch.
    :param session: the database session in use.

    :returns: True if found, otherwise false.
    """

    query = session.query(models.Switch).filter_by(id=id, status=NodeStatus.ACTIVE)

    return True if query.first() else False


@read_session
def get_switch(id, *, session: "Session"):
    """ Returns an switch for the given id.

    :param id: the id of the switch.
    :param session: the database session in use.

    :returns: a dict with all information for the switch.
    """

    query = session.query(models.Switch).filter_by(id=id)

    try:
        result = query.one()
    except exc.NoResultFound:
        raise exception.NodeNotFound(f'Switch with ID {id} cannot be found')

    switch = {}

    if result.system_settings:
        keys = ('type', 'name', 'ID', 'controlInterface', 'queue', 'mode', 'threads', 'workers')
        sys_setting = {k: v for k, v in result.system_settings[0].__dict__.items() if k in keys}
        switch.update({'systemSettings': sys_setting})

    if result.channels:
        channels = []
        channel_keys = ('ID', 'name', 'type', 'direction', 'wavelength', 'power', 'length', 'neighbor')
        for ch in result.channels:
            channel = {k: v for k, v in ch.__dict__.items() if k in channel_keys}
            neighbor_keys = ('idRef', 'systemRef', 'channelRef', 'loss', 'type')
            neighbor = {k: v for k, v in ch.neighbor[0].__dict__.items() if k in neighbor_keys}
            channel.update({'neighbor': neighbor})
            channels.append(channel)
        switch.update({'channels': channels})

    return switch


@transactional_session
def del_switch(id, *, session: "Session"):
    """ Disable a switch with the given id.

    :param id: the switch id.
    :param session: the database session in use.
    """
    query = session.query(models.Switch).filter_by(id=id).filter_by(status=NodeStatus.ACTIVE)
    try:
        switch = query.one()
    except exc.NoResultFound:
        raise exception.NodeNotFound(f'switch with ID {id} cannot be found')

    switch.update({'status': NodeStatus.DELETED, 'deleted_at': datetime.utcnow()})


@transactional_session
def update_switch(id, key, value, *, session: "Session"):
    """ Update a property of an switch.

    :param id: ID of the switch.
    :param key: switch property like status.
    :param value: Property value.
    :param session: the database session in use.
    """
    query = session.query(models.Switch).filter_by(id=id)
    try:
        switch = query.one()
    except exc.NoResultFound:
        raise exception.NodeNotFound(f'switch with ID {id} cannot be found')
    if key == 'status':
        if isinstance(value, str):
            value = NodeStatus[value]
        if value == NodeStatus.SUSPENDED:
            query.update({'status': value, 'suspended_at': datetime.utcnow()})
        elif value == NodeStatus.ACTIVE:
            query.update({'status': value, 'suspended_at': None})
    else:
        switch.update({key: value})

@read_session
def list_switches(filter_=None, *, session: "Session"):
    """ Returns a list of all switch names.

    :param filter_: Dictionary of attributes by which the input data should be filtered
    :param session: the database session in use.

    returns: a list of all switch names.
    """
    if filter_ is None:
        filter_ = {}
    query = session.query(models.Switch).filter_by(status=NodeStatus.ACTIVE)
    for filter_type in filter_:
        if filter_type == 'switch_type':
            if isinstance(filter_['switch_type'], str):
                query = query.filter_by(switch_type=NodeType[filter_['switch_type']])
            elif isinstance(filter_['switch_type'], Enum):
                query = query.filter_by(switch_type=filter_['switch_type'])

        elif filter_type == 'id':
            if '*' in filter_['id'].internal:
                account_str = filter_['id'].internal.replace('*', '%')
                query = query.filter(models.Switch.id.like(account_str))
            else:
                query = query.filter_by(id=filter_['id'])
        else:
            query = query.join(models.SwitchAttr, models.Switch.id == models.SwitchAttr.switch_id).\
                filter(models.SwitchAttr.key == filter_type).\
                filter(models.SwitchAttr.value == filter_[filter_type])

    switch_list = []
    for row in query:
        switch = get_switch(row.id)
        switch_list.append(switch)

    return switch_list
