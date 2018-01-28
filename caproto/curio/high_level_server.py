import logging
import inspect
from collections import (namedtuple, OrderedDict, defaultdict)
from types import MethodType

from .. import (ChannelDouble, ChannelInteger, ChannelString,
                ChannelAlarm)


logger = logging.getLogger(__name__)


class PvpropertyData:
    def __init__(self, *, group, pvspec, **kwargs):
        self.group = group
        self.pvspec = pvspec
        self.getter = (MethodType(pvspec.get, group)
                       if pvspec.get is not None
                       else group.group_read)
        self.putter = (MethodType(pvspec.put, group)
                       if pvspec.put is not None
                       else group.group_write)
        super().__init__(**kwargs)

    async def read(self, data_type):
        value = await self.getter(self)
        if value is not None:
            if self.pvspec.get is None:
                logger.debug('group read value for %s updated: %r',
                             self.pvspec, value)
            else:
                logger.debug('value for %s updated: %r', self.pvspec, value)
            # update the internal state
            await self.write(value)
        return await self._read(data_type)

    async def verify_value(self, value):
        if self.pvspec.put is None:
            logger.debug('group verify value for %s: %r', self.pvspec, value)
        else:
            logger.debug('verify value for %s: %r', self.pvspec, value)
        return await self.putter(self, value)


class PvpropertyInteger(PvpropertyData, ChannelInteger):
    ...


class PvpropertyDouble(PvpropertyData, ChannelDouble):
    ...


class PvpropertyString(PvpropertyData, ChannelString):
    ...


class PVSpec(namedtuple('PVSpec',
                        'get put attr name dtype value alarm_group')):
    'PV information specification'
    __slots__ = ()
    default_dtype = int

    def __new__(cls, get=None, put=None, attr=None, name=None, dtype=None,
                value=None, alarm_group=None):
        if dtype is None:
            dtype = (type(value[0]) if value is not None
                     else cls.default_dtype)

        if get is not None:
            assert inspect.iscoroutinefunction(get), 'required async def get'
            sig = inspect.signature(get)
            try:
                sig.bind('group', 'instance')
            except Exception as ex:
                raise RuntimeError('Invalid signature for getter {}: {}'
                                   ''.format(get, sig))

        if put is not None:
            assert inspect.iscoroutinefunction(put), 'required async def put'
            sig = inspect.signature(put)
            try:
                sig.bind('group', 'instance', 'value')
            except Exception as ex:
                raise RuntimeError('Invalid signature for putter {}: {}'
                                   ''.format(put, sig))

        return super().__new__(cls, get, put, attr, name, dtype, value,
                               alarm_group)

    def new_names(self, attr=None, name=None):
        if attr is None:
            attr = self.attr
        if name is None:
            name = self.name
        return PVSpec(self.get, self.put, attr, name, self.dtype, self.value,
                      self.alarm_group)


class PVFunction:
    'A descriptor for making an RPC-like function'

    def __init__(self, func=None, default=None, alarm_group=None,
                 process_name='Process', return_name='Retval',
                 status_name='Status'):
        self.attr_name = None  # to be set later
        self.default_retval = default
        self.func = func
        self.alarm_group = alarm_group
        self.names = {'process': process_name,
                      'return': return_name,
                      'status': status_name
                      }
        self.pvspec = []

    def __call__(self, func):
        # handles case where PVFunction()(func) is used
        self.func = func
        self.pvspec = self._update_pvspec()
        return self

    def pvspec_from_parameter(self, param):
        dtype = param.annotation
        default = param.default

        try:
            default[0]
        except TypeError:
            default = [default]
        except Exception:
            raise ValueError(f'Invalid default value for parameter {param}')
        else:
            # ensure we copy any arrays as default parameters, lest we give
            # some developers a heart attack
            default = list(default)

        print('pvspec from param', param)
        return PVSpec(
            get=None, put=None, attr=f'{self.attr_name}.{param.name}',
            # TODO: attr_separator
            name=f'{self.attr_name}:{param.name}', dtype=dtype, value=default,
            alarm_group=self.alarm_group,
        )

    def get_additional_parameters(self):
        sig = inspect.signature(self.func)
        return_type = sig.return_annotation
        assert return_type, 'Return value must have a type annotation'

        return [
            inspect.Parameter(self.names['process'], kind=0, default=0,
                              annotation=int),
            inspect.Parameter(self.names['status'], kind=0, default=b'Init',
                              annotation=str),
            inspect.Parameter(self.names['return'], kind=0,
                              # TODO?
                              default=PVGroupBase.default_values[return_type],
                              annotation=return_type),
        ]

    def _update_pvspec(self):
        if self.func is None or self.attr_name is None:
            return []

        if self.alarm_group is None:
            self.alarm_group = self.func.__name__

        sig = inspect.signature(self.func)
        parameters = list(sig.parameters.values())[1:]  # skip 'self'
        parameters.extend(self.get_additional_parameters())
        return [self.pvspec_from_parameter(param) for param in parameters]

    def __get__(self, instance, owner):
        # if instance is None:
        return self.pvspec
        # return instance.attr_pvdb[self.attr_name]
        # return {instance.attr_pvdb[param_name]
        #         for param_name in

    def __set__(self, instance, value):
        instance.attr_pvdb[self.attr_name] = value

    def __delete__(self, instance):
        del instance.attr_pvdb[self.attr_name]

    def __set_name__(self, owner, name):
        self.attr_name = name
        self.pvspec = self._update_pvspec()


class pvproperty:
    'A property-like descriptor for specifying a PV in a group'

    def __init__(self, get=None, put=None, **spec_kw):
        self.attr_name = None  # to be set later
        self.spec_kw = spec_kw
        self.pvspec = PVSpec(get=get, put=put, **spec_kw)

    def __get__(self, instance, owner):
        if instance is None:
            return self.pvspec
        return instance.attr_pvdb[self.attr_name]

    def __set__(self, instance, value):
        instance.attr_pvdb[self.attr_name] = value

    def __delete__(self, instance):
        del instance.attr_pvdb[self.attr_name]

    def __set_name__(self, owner, name):
        self.attr_name = name
        # update the PV specification with the attribute name
        self.pvspec = self.pvspec.new_names(
            self.attr_name,
            self.pvspec.name
            if self.pvspec.name is not None
            else self.attr_name)

    def putter(self, put):
        # update PVSpec with putter
        self.pvspec = PVSpec(self.pvspec.get, put, *self.pvspec[2:])
        return self

    def __call__(self, get, put=None):
        # handles case where pvproperty(**spec_kw)(getter, putter) is used
        self.pvspec = PVSpec(get, put, **self.spec_kw)
        return self


class SubGroup:
    'A property-like descriptor for specifying a subgroup in a PVGroup'

    def __init__(self, group_cls=None, prefix=None, macros=None,
                 attr_separator=None):
        self.attr_name = None  # to be set later
        self.group_cls = group_cls
        self.prefix = prefix
        self.macros = macros if macros is not None else {}
        self.attr_separator = (attr_separator if attr_separator is not None
                               else getattr(group_cls, 'attr_separator', ':'))

    def __get__(self, instance, owner):
        if instance is None:
            return self
        return instance.groups[self.attr_name]

    def __set__(self, instance, value):
        instance.groups[self.attr_name] = value

    def __delete__(self, instance):
        del instance.groups[self.attr_name]

    def __set_name__(self, owner, name):
        self.attr_name = name
        if self.prefix is None:
            self.prefix = name + self.attr_separator

    def __call__(self, group_cls):
        # handles case where SubGroup(**kw)(group_cls) is used
        self.group_cls = group_cls
        return self


def expand_macros(pv, macros):
    'Expand a PV name with Python {format-style} macros'
    return pv.format(**macros)


class PVGroupMeta(type):
    'Metaclass that finds all pvproperties'
    @classmethod
    def __prepare__(self, name, bases):
        # keep class dictionary items in order
        return OrderedDict()

    @staticmethod
    def find_subgroups(dct):
        for attr, value in dct.items():
            if attr.startswith('_'):
                continue

            if isinstance(value, SubGroup):
                yield attr, value

    @staticmethod
    def find_pvproperties(dct):
        for attr, value in dct.items():
            if attr.startswith('_'):
                continue

            if isinstance(value, pvproperty):
                yield attr, value
            elif isinstance(value, SubGroup):
                subgroup_cls = value.group_cls
                for sub_attr, value in subgroup_cls._pvs_.items():
                    yield '.'.join([attr, sub_attr]), value

    def __new__(metacls, name, bases, dct):
        dct['_subgroups_'] = subgroups = OrderedDict()
        for attr, prop in metacls.find_subgroups(dct):
            logger.debug('class %s attr %s: %r', name, attr, prop)
            subgroups[attr] = prop

            # TODO a bit messy
            # propagate subgroups-of-subgroups to the top
            subgroup_cls = prop.group_cls
            if hasattr(subgroup_cls, '_subgroups_'):
                for subattr, subgroup in subgroup_cls._subgroups_.items():
                    subgroups['.'.join((attr, subattr))] = subgroup

        dct['_pvs_'] = pvs = OrderedDict()
        for attr, prop in metacls.find_pvproperties(dct):
            logger.debug('class %s attr %s: %r', name, attr, prop)
            pvs[attr] = prop

        return super().__new__(metacls, name, bases, dct)


def channeldata_from_pvspec(group, pvspec):
    'Create a ChannelData instance based on a PVSpec'
    full_pvname = expand_macros(group.prefix + pvspec.name, group.macros)
    value = (pvspec.value
             if pvspec.value is not None
             else group.default_values[pvspec.dtype]
             )

    cls = group.type_map[pvspec.dtype]
    inst = cls(group=group, pvspec=pvspec,
               value=value, alarm=group.alarms[pvspec.alarm_group])
    return (full_pvname, inst)


class PVGroupBase(metaclass=PVGroupMeta):
    'Base class for a group of PVs'
    type_map = {
        str: PvpropertyString,
        int: PvpropertyInteger,
        float: PvpropertyDouble,
    }

    default_values = {
        str: '-',
        int: 0,
        float: 0.0,
    }

    def __init__(self, prefix, macros=None):
        self.macros = macros if macros is not None else {}
        self.prefix = expand_macros(prefix, self.macros)
        self.alarms = defaultdict(lambda: ChannelAlarm())
        self.pvdb = OrderedDict()
        self.attr_pvdb = OrderedDict()
        self.groups = OrderedDict()
        self._create_pvdb()

    def _create_pvdb(self):
        'Create the PV database for all subgroups and pvproperties'
        for attr, subgroup in self._subgroups_.items():
            subgroup_cls = subgroup.group_cls

            prefix = (subgroup.prefix if subgroup.prefix is not None
                      else subgroup.prefix)
            prefix = self.prefix + prefix

            macros = dict(self.macros)
            macros.update(subgroup.macros)

            self.groups[attr] = subgroup_cls(prefix=prefix, macros=macros)

        for attr, pvprop in self._pvs_.items():
            if '.' in attr:
                group_attr, _ = attr.rsplit('.', 1)
                group = self.groups[group_attr]
            else:
                group = self

            pvname, channeldata = channeldata_from_pvspec(group, pvprop.pvspec)

            # full pvname -> ChannelData instance
            self.pvdb[pvname] = channeldata

            # attribute -> PV instance mapping for quick access by pvproperty
            self.attr_pvdb[attr] = channeldata

    async def group_read(self, instance):
        'Generic read called for channels without `get` defined'
        logger.debug('no-op group read of %s', instance.pvspec.attr)

    async def group_write(self, instance, value):
        'Generic write called for channels without `put` defined'
        logger.debug('group write of %s = %s', instance.pvspec.attr, value)
        return value
