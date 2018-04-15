import sys
import wrappers

import piqi_of_piq
import piqi_of_json
import piqi_to_json


# parse state
#
# TODO: make it less hacky
_parse_piqi_module = None


class ObjectProxy(wrappers.ObjectProxy):
    def __init__(self, wrapped, piqi_type, loc):
        super(ObjectProxy, self).__init__(wrapped)
        self._self_loc = loc
        self._self_piqi_type = piqi_type
        self._self_piqi_module = _parse_piqi_module

    @property
    def __loc__(self):
        return self._self_loc

    @property
    def __piqi_type__(self):
        return self._self_piqi_type

    @property
    def __piqi_module__(self):
        return self._self_piqi_module

    def __repr__(self):
        return repr(self.__wrapped__)


def unwrap_object(x):
    if isinstance(x, ObjectProxy):
        return unwrap_object(x.__wrapped__)
    else:
        return x


def make_record(fields, piqi_type, loc=None):
    obj = Record(fields)
    return ObjectProxy(obj, piqi_type, loc)

def make_list(items, piqi_type, loc=None):
    obj = List(items)
    return ObjectProxy(obj, piqi_type, loc)

def make_variant(tag, value, piqi_type, loc=None):
    obj = Variant((Tag(tag), value))
    return ObjectProxy(obj, piqi_type, loc)

def make_enum(tag, piqi_type, loc=None):
    obj = Enum(tag)
    return ObjectProxy(obj, piqi_type, loc)

def make_scalar(value, loc=None):
    # XXX: why piqi_type would be None?
    return ObjectProxy(value, None, loc)

def make_any(loc=None, **kwargs):
    obj = Any(**kwargs)
    return ObjectProxy(obj, 'piqi-any', loc)


# representation of a generic piqi object
#
# as e.g. returned by piqi_of_piq.parse()

class Record(object):
    def __init__(self, fields):
        for name, value in fields:
            self.__setattr__(name, value)

    def __repr__(self):
        return repr(vars(self))


class List(list):
    pass


class Variant(tuple):
    pass


# TODO, XXX: what about aliases? we should probably support them as well


# XXX: anything else? int code?
class Tag(str):
    # overriding str "constructor", for details see https://stackoverflow.com/questions/7255655/how-to-subclass-str-in-python/33272874#33272874
    def __new__(cls, x):
        return super(Tag, cls).__new__(cls, make_name(x))


class Enum(Tag):
    pass


def make_name(x):
    return str(x).replace('-', '_')


def make_field_name(field_spec):
    piqi_name = name_of_field(field_spec)
    name = make_name(piqi_name)
    if field_spec['mode'] == 'repeated':
        name = name + '_list'
    return name


class Any(object): 
    def __init__(self, typename=None, piq_ast=None, json_ast=None):
	self.typename = typename
	self.piq_ast = piq_ast
	self.json_ast = json_ast
	self.obj = None

    def __repr__(self):
        return repr(vars(self))


#class ParseError(Exception):
class ParseError(RuntimeError):
    def __init__(self, loc, error):
        line = str(loc.line) if loc else 'unknown'
        RuntimeError.__init__(self, line + ': ' + error)
        self.error = error
        self.loc = loc
    def __repr__(self):
        return error


# return one of built-in types, or None for user-defined types
#
# TODO: don't hardcode built-in piqi types, grab them from piqi self-spec as
# others piqic do
def get_piqi_type(typename):
    piqi_type = None
    if typename == 'bool':
        piqi_type = 'bool'
    elif typename == 'string':
        piqi_type = 'string'
    elif typename == 'binary':
        piqi_type = 'binary'
    elif typename == 'piqi-any':
        piqi_type = 'any'
    elif typename in ('int', 'uint',
                        'int32', 'uint32',
                        'int64', 'uint64',
                        'int32-fixed', 'uint32-fixed',
                        'int64-fixed', 'uint64-fixed',
                        'protobuf-int32', 'protobuf-int64'):
        piqi_type = 'int'
    elif typename in ('float32', 'float64', 'float'):
        piqi_type = 'float'
    return piqi_type


def is_piqi_type(typename):
    return (get_piqi_type(typename) is not None)


# TODO: fix code duplication with piqi_of_piq
def name_of_field(t):
    return t.get('name', t.get('type'))


def name_of_option(t):
    return t.get('name', t.get('type'))


def unalias(typename):
    piqi_type = get_piqi_type(typename)
    if piqi_type:
        return piqi_type, None
    else:
        type_tag, typedef = res = resolve_type(typename)
        if type_tag == 'alias':
            return unalias(typedef['type'])
        else:
            return res


# resolve user-defined type
def resolve_type(typename, piqi_module=None):
    if piqi_module is None:
        piqi_module = _parse_piqi_module
    return piqi_module.typedef_index[typename]


def parse(x, module_name, typename, format='piq'):
    # init parsing state
    global _parse_piqi_module
    _parse_piqi_module = sys.modules[module_name]

    if format == 'piq':
        return piqi_of_piq.parse(typename, x)
    elif format == 'json':
        return piqi_of_json.parse(typename, x)
    else:
        assert False


def gen(x, format='json'):
    if format == 'json':
        return piqi_to_json.gen(x)
    else:
        assert False
