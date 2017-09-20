import collections
import base64
import wrappers

import piqi
import piqi_of_json


# config
#
# TODO: make configurable
omit_missing_fields = True


def omit_missing_field(f):
    return f.get('json_omit_missing', omit_missing_fields)


def resolve_type(x):
    return piqi.resolve_type(x.__piqi_type__, x.__piqi_module__)


# top-level call
def gen(x):
    return gen_obj(x)


def gen_obj(x):
    if isinstance(x, piqi.List):
        return gen_list(x)
    elif isinstance(x, piqi.Record):
        return gen_record(x)
    elif isinstance(x, piqi.Enum):
        return gen_enum(x)
    elif isinstance(x, piqi.Variant):
        return gen_variant(x)
    elif isinstance(x, piqi.Any):
        return gen_any(x)
    elif isinstance(x, (bool, int, float, basestring)):
        # TODO: binary -> base64
        return piqi.unwrap_object(x)
    else:
        # TODO, XXX: piqi.Alias?
        assert False


def gen_any(x):
    # TODO: resolve + piq & other representations
    res = [('piqi_type', 'piqi-any')]

    if x.typename is not None:
        res.append(('type', x.typename))

    if x.json_ast is not None:
        res.append(('json', x.json_ast))

    return collections.OrderedDict(res)


def gen_list(x):
    return [gen_obj(item) for item in x]


def gen_record(x):
    type_tag, record_spec = resolve_type(x)
    field_spec_list = record_spec['field']
    fields = []
    for field_spec in field_spec_list:
        skip, value = gen_field(field_spec, x)

        if not skip:
            json_name = piqi_of_json.json_name_of_field(field_spec)
            fields.append((json_name, value))

    return collections.OrderedDict(fields)


def gen_field(field_spec, record):
    field_name = piqi.make_field_name(field_spec)
    field_value = getattr(record, field_name)
    field_mode = field_spec['mode']
    omit_missing = omit_missing_field(field_spec)

    if field_mode == 'repeated':
        assert isinstance(field_value, list)

        skip = (omit_missing and field_value == [])

        return skip, [gen_obj(x) for x in field_value]

    elif field_mode == 'required':
        assert (field_value is not None)

        skip = False
        return skip, gen_obj(field_value)

    elif field_mode == 'optional':
        if field_value is None:
            skip = omit_missing

            return skip, None

        elif field_spec.get('type') is None:  # flag
            # TODO, XXX: we want to revisit flag handling, should they be really
            # treated specially or they are just a shorthand for optional bool
            # with default = false
            skip = (omit_missing and field_value == False)

            return skip, field_value

        else:
            skip = False
            return skip, gen_obj(field_value)
    else:
        assert False


def gen_variant(x):
    tag, value = x

    option_spec = find_option_spec(x, tag)
    json_name = piqi_of_json.json_name_of_option(option_spec)

    if value is None:
        if option_spec.get('type') is not None:
            json_value = None
        else:
            json_value = True  # flag
    else:
        json_value = gen_obj(value)

    return {json_name : json_value}


def find_option_spec(x, tag):
    # TODO, XXX: is there a more efficient way to retrieve option name? 
    type_tag, variant_or_enum_spec = resolve_type(x)
    option_spec_list = variant_or_enum_spec['option']

    for option_spec in option_spec_list:
        if piqi.make_name(piqi.name_of_option(option_spec)) == tag:
            return option_spec

    assert False  # unknown option


def gen_enum(x):
    option_spec = find_option_spec(x, x)
    json_name = piqi_of_json.json_name_of_option(option_spec)

    return json_name
