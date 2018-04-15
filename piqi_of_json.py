import base64

import piqi


# state
#
# TODO, XXX: wrap in a Parser class?


# NOTE: there is no location info in Python's decoded json objects
#
# XXX: provide some other form of context like path, e.g. foo[3].bar ?
class ParseError(Exception):
    def __init__(self, error):
        self.error = error


# top-level call
def parse(typename, x):
    # XXX: remove top-level piqi_type
    if isinstance(x, dict) and 'piqi_type' in x:
        x = x.copy()
        del x['piqi_type']

    # convert .ParseError into piqi.ParseError
    try:
        return parse_obj(typename, x)
    except ParseError as e:
        # NOTE: there are no locations in Python's json objects
        raise piqi.ParseError(None, e.error)


def parse_obj(typename, x):
    piqi_type = piqi.get_piqi_type(typename)
    if piqi_type:  # one of built-in types
        if piqi_type == 'bool':
            return parse_bool(x)
        elif piqi_type == 'int':
            return parse_int(x)
        elif piqi_type == 'float':
            return parse_float(x)
        elif piqi_type == 'string':
            return parse_string(x)
        elif piqi_type == 'binary':
            return parse_binary(x)
        elif piqi_type == 'any':
            return parse_any(x)
        else:
            assert False
    else:  # user-defined type
        type_tag, typedef = piqi.resolve_type(typename)
        if type_tag == 'record':
            return parse_record(typedef, x)
        elif type_tag == 'list':
            return parse_list(typedef, x)
        elif type_tag == 'variant':
            return parse_variant(typedef, x)
        elif type_tag == 'enum':
            return parse_enum(typedef, x)
        elif type_tag == 'alias':
            return parse_alias(typedef, x)
        else:
            assert False


def parse_list(t, x):
    if isinstance(x, list):
        item_type = t['type']
        l = x
        items = [parse_obj(item_type, x) for x in l]
        return piqi.make_list(items, t['name'])
    else:
        raise ParseError('array expected')


def parse_record(t, x):
    if isinstance(x, dict):
        l = x.items()
    else:
        raise ParseError('array expected')

    return do_parse_record(t, l)


def do_parse_record(t, l):
    field_spec_list = t['field']

    parsed_fields = []
    for field_spec in field_spec_list:
        value, l = parse_field(field_spec, l)

        name = piqi.make_field_name(field_spec)

        parsed_fields.append((name, value))

    for x in l:
        raise ParseError('unknown field: ' + str(x))

    return piqi.make_record(parsed_fields, t['name'])


def parse_field(t, l):
    #print 'parse field', piqi.name_of_field(t), l

    if t.get('type'):
        return do_parse_field(t, l)
    else:
        return do_parse_flag(t, l)


def quote(name):
    return "'" + name + "'"


def do_parse_flag(t, l):
    name = json_name_of_field(t)
    res, rem = find_flag(name, l)
    if res is None:
        # missing flag implies False value
        return piqi.make_scalar(False), rem
    else:
        return piqi.make_scalar(res), rem


def do_parse_field(t, l):
    name = json_name_of_field(t)
    field_type = t['type']
    field_mode = t['mode']
    if field_mode == 'required':
        return parse_required_field(name, field_type, l)
    elif field_mode == 'optional':
        return parse_optional_field(name, field_type, t.get('default'), l)
    elif field_mode == 'repeated':
        return parse_repeated_field(name, field_type, l)
    else:
        assert False


def parse_required_field(name, field_type, l, loc=None):
    res, rem = find_field(name, l)
    if res is None:
        raise ParseError('missing field ' + quote(name))
    else:
        obj = parse_obj(field_type, res)
        return obj, rem


def parse_optional_field(name, field_type, default, l):
    res, rem = find_field(name, l)
    if res is None:
        obj = parse_default(field_type, default)
        return obj, l
    else:
        obj = parse_obj(field_type, res)
        return obj, rem


def parse_repeated_field(name, field_type, l):
    res, rem = find_field(name, l)
    if res is None:
        return [], rem
    else:
        if not isinstance(res, list):
            raise ParseError('array expected for field ' + quote(name))
        items = [parse_obj(field_type, x) for x in res]
        return items, rem


def parse_default(field_type, default):
    if default is None:
        return None
    else:
        # TODO, XXX: parse default in piqic-python instead of runtime
        json = default['json']
        return parse_obj(field_type, json)


# find field by name, return found field and remaining fields
def find_field(name, l):
    res = None
    rem = []
    for item in l:
        if res is not None:
            rem.append(item)
        else:
            n, v = item
            if n == name:
                res = v
            else:
                rem.append(item)
    return res, rem


# find flag by name, return found flag and remaining fields
def find_flag(name, l):
    res = None
    rem = []
    for item in l:
        if res is not None:
            rem.append(item)
        else:
            n, v = item
            if n == name:
                if not isinstance(v, bool):
                    raise ParseError('only true and false can be used as values for flag ' + quote(name))
                res = v
            else:
                rem.append(item)
    return res, rem


def parse_enum(t, x):
    option_spec_list = t['option']
    if isinstance(x, basestring):
        for o in option_spec_list:
            option_name = json_name_of_option(o)
            if option_name == x:
                return piqi.make_enum(piqi.name_of_option(o), t['name'])
        raise ParseError("unknown enum option " + quote(x))
    else:
        raise ParseError('string enum value expected')


def parse_variant(t, x):
    option_spec_list = t['option']
    if isinstance(x, dict):
        l = x.items()
        if len(l) != 1:
            raise ParseError('exactly one option field expected')
        n, v = l[0]
        for o in option_spec_list:
            option_name = json_name_of_option(o)
            if option_name == n:
                value = parse_option(o, v)
                return piqi.make_variant(piqi.name_of_option(o), value, t['name'])
        raise ParseError('unknown variant option ' + quote(n))
    else:
        raise ParseError('object expected')


def parse_option(t, x):
    option_type = t.get('type')
    if option_type is None:
        if x == True:
            return None
        else:
            raise ParseError('True value expected')
    else:
        return parse_obj(option_type, x)


def parse_alias(t, x):
    alias_type = t['type']
    return parse_obj(alias_type, x)


def parse_bool(x):
    if isinstance(x, bool):
        return piqi.make_scalar(x)
    else:
        raise ParseError('bool constant expected')


def parse_int(x):
    if isinstance(x, int):
        return piqi.make_scalar(x)
    else:
        raise ParseError('int constant expected')


def parse_float(x):
    if isinstance(x, float):
        return piqi.make_scalar(x)
    elif isinstance(x, int):
        return piqi.make_scalar(x * 1.0)
    elif x == 'NaN':
        return piqi.make_scalar(float("nan"))
    elif x == 'Infinity':
        return piqi.make_scalar(float("inf"))
    elif x == '-Infinity':
        return piqi.make_scalar(-float("inf"))
    else:
        raise ParseError('float constant expected')


def parse_string(x):
    if isinstance(x, basestring):
        # TODO: check for correct unicode
        return piqi.make_scalar(x)
    else:
        raise ParseError('string constant expected')


def parse_binary(x):
    if isinstance(x, basestring):
        try:
            value = base64.b64decode(x)
            return piqi.make_scalar(value)
        except:
            ParseError('invalid base64-encoded string')
    else:
        raise ParseError('string constant expected')


def parse_any(x):
    if isinstance(x, dict) and x.get('piqi_type') == 'piqi-any': # extended piqi-any format
        # manually parsing the piqi-any record, so that we could extract the
        # symbolic json representation

        typename = x.get('type')
        assert isinstance(typename, basestring)

        json_ast = x.get('json')

        # TODO, XXX: other fields such as pb and piq
        return piqi.make_any(typename=typename, json_ast=json_ast)

    else: # regular symbolic piqi-any
        return piqi.make_any(json_ast=x)


def json_name_of_option(t):
    json_name = t.get('json_name')
    if json_name is None:
        json_name = make_json_name(piqi.name_of_option(t))
    return json_name


def json_name_of_field(t):
    json_name = t.get('json_name')
    if json_name is None:
        json_name = make_json_name(piqi.name_of_field(t))
        # TODO
        #if t['mode'] == 'repeated':
        #    json_name += '_list'
    return json_name


def make_json_name(x):
    return str(x).replace('-', '_')
