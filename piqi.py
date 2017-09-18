import wrappers
import piq


class ObjectProxy(wrappers.ObjectProxy):
    def __init__(self, wrapped, loc, piqi_type):
        super(ObjectProxy, self).__init__(wrapped)
        self._self_loc = loc
        self._self_piqi_type = piqi_type

    @property
    def __loc__(self):
        return self._self_loc

    @property
    def piqi_type(self):
        return self._self_piqi_type

    def __repr__(self):
        return repr(self.__wrapped__)


def make_name(x):
    return str(x).replace('-', '_')


class Record(object):
    def __init__(self, fields):
        self._field_names = []
        for name, value in fields:
            name = make_name(name)
            self.__setattr__(name, value)
            self._field_names.append(name)

    @property
    def _fields(self):
        fields = []
        for name in self._field_names:
            value = getattr(self, name)
            if value is not None:
                fields.append((name, value))
        return dict(fields)

    def __repr__(self):
        return repr(self._fields)


def make_record(fields, loc, piqi_type):
    record = Record(fields)
    return ObjectProxy(record, loc, piqi_type)

def make_list(items, loc, piqi_type):
    return ObjectProxy(items, loc, piqi_type)


# XXX: anything else? int code?
class Tag(str):
    pass

def make_tag(x):
    return Tag(make_name(x))


def make_variant(tag, value, loc, piqi_type):
    variant = (make_tag(tag), value)
    return ObjectProxy(variant, loc, piqi_type)

def make_enum(tag, loc, piqi_type):
    enum = make_tag(tag)
    return ObjectProxy(enum, loc, piqi_type)

def make_scalar(value, loc):
    return ObjectProxy(value, loc, piqi_type=None)


# parsing state
#
# TODO, XXX: wrap in a PiqiParser class?
_depth = 0
_typedef_index = None

# parsing config
#
# TODO: make configurable
piq_relaxed_parsing = True


# resolve user-defined type
def resolve_type(typename):
    return _typedef_index[typename]


# top-level call
def parse(typename, x, typedef_index):
    # init parsing state
    global _typedef_index, _depth
    _typedef_index = typedef_index
    _depth = 0

    # XXX: convert piq.ParseError into piqi.ParseError
    try:
        piq_ast = piq.parse(x, expand_splices=True, expand_names=True)
    except piq.ParseError as e:
        raise ParseError(e.loc, e.error)

    return parse_obj(typename, piq_ast)


#class ParseError(Exception):
class ParseError(RuntimeError):
    def __init__(self, loc, error):
        RuntimeError.__init__(self, str(loc.line) + ': ' + error)
        self.depth = _depth
        self.error = error
        self.loc = loc
    def __repr__(self):
        return error


def parse_obj(typename, x, try_mode=False, nested_variant=False, labeled=False, typedef_index=None):
    piqi_type = get_piqi_type(typename)
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
        type_tag, typedef = resolve_type(typename)
        if type_tag == 'record':
            return parse_record(typedef, x, labeled=labeled)
        elif type_tag == 'list':
            return parse_list(typedef, x)
        elif type_tag == 'variant':
            return parse_variant(typedef, x, try_mode=try_mode, nested_variant=nested_variant)
        elif type_tag == 'enum':
            return parse_enum(typedef, x, try_mode=try_mode, nested_variant=nested_variant)
        elif type_tag == 'alias':
            return parse_alias(typedef, x, try_mode=try_mode, nested_variant=nested_variant, labeled=labeled)
        else:
            assert False


def parse_list(t, x):
    if isinstance(x, piq.List):
        # TODO: fix this ugliness, for parse_record too
        global _depth
        _depth += 1
        res = do_parse_list(t, l, loc=x.loc)
        _depth -= 1;
        return res
    else:
        raise ParseError(x.loc, 'list expected')


def do_parse_list(t, l, loc=None):
    item_type = t['type']
    items = [parse_obj(item_type, x) for x in l]
    return make_list(items, loc, t['name'])


def parse_record(t, x, labeled=False):
    if isinstance(x, piq.List):
        l = x.items
        loc = x.loc
    elif labeled and t.get('piq_allow_unnesting'):
        # allow field unnesting for a labeled record
        l = [x]
        loc = x.loc
    else:
        raise ParseError(x.loc, 'list expected')

    global _depth
    _depth += 1
    # NOTE: pass locating information as a separate parameter since empty
    # list is unboxed and doesn't provide correct location information
    res = do_parse_record(t, l, loc=loc)
    _depth -= 1;
    return res


def do_parse_record(t, l, loc=None):
    field_spec_list = t['field']

    # parse required fields first
    required, optional = [], []
    for f in field_spec_list:
        (optional, required)[f['mode'] == 'required'].append(f)
    field_spec_list = required + optional

    parsed_fields = []
    for field_spec in field_spec_list:
        value, l = parse_field(field_spec, l, loc=loc)

        name = name_of_field(field_spec)
        if field_spec['mode'] == 'repeated':
            name = name + '_list'

        parsed_fields.append((name, value))

    for x in l:
        raise ParseError(x.loc, 'unknown field: ' + str(x))

    return make_record(parsed_fields, loc, t['name'])


def parse_field(t, l, loc=None):
    #print 'parse field', name_of_field(t), l

    if t.get('type'):
        return do_parse_field(t, l, loc=loc)
    else:
        return do_parse_flag(t, l, loc=loc)


def maybe_report_duplicate_field(name, l):
    # TODO: warnings on several duplicates fields
    if len(l) > 1:
        raise ParseError(l[1].loc, 'duplicate field ' + quote(name))


def quote(name):
    return "'" + name + "'"


def do_parse_flag(t, l, loc=None):
    name = name_of_field(t)
    # NOTE: flags can't be positional so we only have to look for them by name
    res, rem = find_flags(name, t.get('piq_alias'), l)
    if res == []:
        # missing flag implies False value
        return make_scalar(False, loc), rem
    else:
        x = res[0]
        maybe_report_duplicate_field(name, res)
        if isinstance(x, piq.Name) or (isinstance(x, piq.Named) and isinstance(x.value, piq.Scalar) and x.value.value == True):
            # flag is considered as present when it is represented either as name
            # w/o value or named boolean true value
            return make_scalar(True, loc), rem
        elif isinstance(x, piq.Named) and isinstance(x.value, piq.Scalar) and x.value.value == False:
             # flag is considered missing/unset when its value is false
             return make_scalar(False, loc), rem
        else:
             # there are no other possible representations of flags
             assert False


def do_parse_field(t, l, loc=None):
    name = name_of_field(t)
    field_type = t['type']
    field_mode = t['mode']
    if field_mode == 'required':
        return parse_required_field(t, name, field_type, l, loc=loc)
    elif field_mode == 'optional':
        return parse_optional_field(t, name, field_type, t.get('default'), l)
    elif field_mode == 'repeated':
        return parse_repeated_field(t, name, field_type, l)
    else:
        assert False


def parse_required_field(t, name, field_type, l, loc=None):
    res, rem = find_fields(name, t.get('piq_alias'), field_type, l)
    if res == []:
        # try finding the first field which is successfully parsed by
        # 'parse_obj' for a given field type
        res, rem = find_first_parsed_field(t, field_type, l)
        if res is None:
            raise ParseError(loc, 'missing field ' + quote(name))
        else:
            return res, rem
    else:
        x = res[0]
        maybe_report_duplicate_field(name, res)
        obj = parse_obj(field_type, x, labeled=True)
        return obj, rem


def parse_optional_field(t, name, field_type, default, l):
    res, rem = find_fields(name, t.get('piq_alias'), field_type, l)
    if res == []:
        # try finding the first field which is successfully parsed by
        # 'parse_obj' for a given field type
        res, rem = find_first_parsed_field(t, field_type, l)
        if res is None:
            res = parse_default(field_type, default)
            return res, l
        else:
            return res, rem
    else:
        x = res[0]
        maybe_report_duplicate_field(name, res)
        obj = parse_obj(field_type, x, labeled=True)
        return obj, rem


def parse_repeated_field(t, name, field_type, l):
    res, rem = find_fields(name, t.get('piq_alias'), field_type, l)
    if res == []:
        # XXX: ignore errors occurring when unknown element is present in the
        # list allowing other fields to find their members among the list of
        # elements
        res, rem = find_all_parsed_fields(t, field_type, l)
        return res, rem
    else:
        # use strict parsing
        res = [parse_obj(field_type, x, labeled=True) for x in res]
        return res, rem


def parse_default(field_type, default):
    if default is None:
        return None
    else:
        piq_ast = default_to_piq(default['json'])
        return parse_obj(field_type, piq_ast)


# TODO, XXX: do this conversion in piqic-python instead of runtime
#
# TODO: default records with repeated fields are handled incorrectly -- we need
# piqobj_of_piq.py for that
def default_to_piq(x):
    if isinstance(x, list):
        items = [default_to_piq(item) for item in x]
        return piq.List(items, None)
    elif isinstance(x, dict):
        items = [piq.Named(k, None, default_to_piq(v)) for k, v in x.items()]
        return piq.List(items, None)
    else:  # scalar
        return piq.Scalar(x, None)


def find_first_parsed_field(t, field_type, l):
    res = None
    rem = []
    for x in l:
        if res:
            # already found => copy the reminder
            rem.append(x)
        else:
            obj = try_parse_field(t, field_type, x)
            if obj:  # found
                res = obj
            else:
                rem.append(x)
    return res, rem


def find_all_parsed_fields(t, field_type, l):
    res = []
    rem = []
    for x in l:
        obj = try_parse_field(t, field_type, x)
        if obj:
            res.append(obj)
        else:
            rem.append(x)
    return res, rem


def try_parse_field(field_spec, field_type, x):
    type_tag, typedef = unalias(field_type)
    piq_positional = field_spec.get('piq_positional')
    if piq_positional == False:
        # this field must be always labeled according to the explicit
        # ".piq-positional false"
        return None
    elif not piq_positional and type_tag in ('record', 'list'):
        # all records and lists should be labeled (i.e. can't be positional)
        # unless explicitly overridden in the piqi spec by ".piq-positional
        # true"
        return None
    elif type_tag == 'any' and not field_type.get('name'):
        # NOTE, XXX: try-parsing of labeled any always failes
        return None
    # NOTE, XXX: try-parsing of unlabeled `any always succeeds
    else:
        global _depth
        depth = _depth
        try:
            return parse_obj(field_type, x, try_mode=True)
        except ParseError as e:
            # ignore errors which occur at the same parse depth, i.e. when
            # parsing everything except for lists and records which increment
            # depth
            if e.depth == depth:
                # restore the original depth
                _depth = depth
                return None


# find field by name, return found fields and remaining fields
def find_fields(name, alt_name, field_type, l):
    def name_matches(n):
        return (n == name or n == alt_name)
    res = []
    rem = []
    for x in l:
        if isinstance(x, piq.Named) and name_matches(x.name):
            res.append(x.value)
        elif isinstance(x, piq.Name) and name_matches(x.name):
            type_tag, typedef = unalias(field_type)
            if type_tag == 'bool':
                # allow omitting boolean constant for a boolean field by
                # interpreting the missing value as "true"
                piq_ast = piq.Scalar(True, x.loc)
                res.append(piq_ast)
            else:
                raise ParseError(x.loc, 'value must be specified for field ' + quote(x.name))
        else:
            rem.append(x)
    return res, rem


# find flags by name, return found flags and remaining fields
def find_flags(name, alt_name, l):
    def name_matches(n):
        return (n == name or n == alt_name)
    res = []
    rem = []
    for x in l:
        if isinstance(x, piq.Name) and name_matches(x.name):
            res.append(x)
        elif isinstance(x, piq.Named) and name_matches(x.name):
            # allow specifying true or false as flag values: true will be
            # interpreted as flag presence, false is treated as if the flag was
            # missing
            if isinstance(x.value.value, bool):
                res.append(x)
            else:
                raise ParseError(x.loc, 'only true and false can be used as values for flag ' + quote(x.name))
        else:
            rem.append(x)
    return res, rem


def parse_variant(t, x, try_mode=False, nested_variant=False):
    option_spec_list = t['option']
    tag, value = parse_options(option_spec_list, x, try_mode=try_mode, nested_variant=nested_variant)
    return make_variant(tag, value, x.loc, t['name'])


def parse_enum(t, x, try_mode=False, nested_variant=False):
    option_spec_list = t['option']
    tag, _ = parse_options(option_spec_list, x, try_mode=try_mode, nested_variant=nested_variant)
    return make_enum(tag, x.loc, t['name'])


class UnknownVariant(Exception):
    pass


def parse_options(option_spec_list, x, try_mode=False, nested_variant=False):
    for option_spec in option_spec_list:
        res = parse_option(option_spec, x, try_mode=try_mode)
        if res is not None:  # success
            return res
        else:
            res = parse_nested_option(option_spec, x, try_mode=try_mode)
            if res is not None:
                return res
            else:
                # continue with other options
                pass

    # none of the options matches
    if nested_variant:
        raise UnknownVariant
    else:
        raise ParseError(x.loc, 'unknown variant: ' + str(x))


def parse_option(t, x, try_mode=False):
    if isinstance(x, piq.Name):
        return parse_name_option(t, x.name, loc=x.loc)
    elif isinstance(x, piq.Named):
        return parse_named_option(t, x.name, x.value, loc=x.loc)
    else:
        return parse_option_by_type(t, x, try_mode=try_mode)


# recursively descent into non-terminal (i.e. nameless variant and enum) options
#
# NOTE: recurse into aliased nested variants as well
def parse_nested_option(t, x, try_mode=False):
    option_name = name_of_option(t)
    option_type = t.get('type')
    if t.get('name') is None and option_type:
        type_tag, typedef = unalias(option_type)
        is_nested_variant = (type_tag == 'variant' or type_tag == 'enum')
        if is_nested_variant:
            try:
                tag = option_name
                value = parse_obj(option_type, x, try_mode=try_mode, nested_variant=True)
                return tag, value
            except UnknownVariant:
                pass
    return None


def parse_name_option(t, name, loc=None):
    option_name = name_of_option(t)
    if name == option_name or name == t.get('piq_alias'):
        option_type = t.get('type')
        if option_type:
            raise ParseError(loc, 'value expected for option ' + quote(name))
        else:
            tag = option_name
            value = None
            return tag, value

    else:
        return None


def parse_named_option(t, name, x, loc=None):
    option_name = name_of_option(t)
    if name == option_name or name == t.get('piq_alias'):
        option_type = t.get('type')
        if not option_type:
            raise ParseError(loc, 'value can not be specified for option ', quote(name))
        else:
            tag = option_name
            value = parse_obj(option_type, x, labeled=True)
            return tag, value
    else:
        return None


def parse_option_by_type(t, x, try_mode=False):
    option_name = t.get('name')
    option_type = t.get('type')
    if option_name and not option_type:
        # try parsing word as a name, but only when the label is exact, i.e.
        # try_mode = false
        # 
        # by doing this, we allow using --foo bar instead of --foo.bar in
        # relaxed piq parsing and getopt modes
        if isinstance(x, piq.Scalar) and isinstance(x.value, basestring):
            word = x.value
            if (word == option_name or word == t.get('piq_alias')) and piq_relaxed_parsing and not try_mode:
                tag = option_name
                value = None
                return tag, value
            else:
                return None
        else:
            return None
    elif option_type:
        parse = False
        type_tag, typedef = unalias(option_type)
        if isinstance(x, piq.Scalar):
            if type_tag == 'bool' and isinstance(x.value, bool):
                parse = True
            elif type_tag == 'int' and isinstance(x.value, int):
                parse = True
            elif type_tag == 'float' and isinstance(x.value, (int, float)):
                parse = True
            elif type_tag == 'string' and isinstance(x.value, basestring):
                parse = True
            elif type_tag == 'string' and isinstance(x.value, (int, uint, float, bool)) and piq_relaxed_parsing:
                parse = True
            elif type_tag == 'binary' and isinstance(x.value, basestring):
                parse = True
        elif type_tag in ('record', 'list') and isinstance(x, piq.List):
            parse = True

        if parse:
            tag = name_of_option(t)
            value = parse_obj(option_type, x)
            return tag, value
        else:
            return None
    else:
        assert False


def parse_alias(t, x, try_mode=False, nested_variant=False, labeled=False):
    alias_type = t['type']
    return parse_obj(alias_type, x, try_mode=try_mode, nested_variant=nested_variant, labeled=labeled)


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


def name_of_field(t):
    return t.get('name', t.get('type'))


def name_of_option(t):
    return t.get('name', t.get('type'))


def parse_bool(x):
    if isinstance(x, piq.Scalar) and isinstance(x.value, bool):
        return make_scalar(x.value, x.loc)
    else:
        raise ParseError(x.loc, 'bool constant expected')


def parse_int(x):
    if isinstance(x, piq.Scalar) and isinstance(x.value, int):
        return make_scalar(x.value, x.loc)
    else:
        raise ParseError(x.loc, 'int constant expected')


def parse_float(x):
    if isinstance(x, piq.Scalar) and isinstance(x.value, float):
        return make_scalar(x.value, x.loc)
    elif isinstance(x, piq.Scalar) and isinstance(x.value, int):
        return make_scalar(x.value * 1.0, x.loc)
    else:
        raise ParseError(x.loc, 'float constant expected')


def parse_string(x):
    if isinstance(x, piq.Scalar) and isinstance(x.value, basestring):
        # TODO: check for correct unicode
        return make_scalar(x.value, x.loc)
    elif isinstance(x, piq.Scalar) and isinstance(x.value, (int, float)) and piq_relaxed_parsing:
        return make_scalar(str(x.value), x.loc)
    elif isinstance(x, piq.Scalar) and isinstance(x.value, bool) and piq_relaxed_parsing:
        if x.value:
            return make_scalar('true', x.loc)
        else:
            return make_scalar('false', x.loc)
    else:
        raise ParseError(x.loc, 'string expected')


def parse_binary(x):
    if isinstance(x, piq.Scalar) and isinstance(x.value, basestring):
        # TODO: check for 8-bit characters
        return make_scalar(x.value, x.loc)
    else:
        raise ParseError(x.loc, 'binary expected')


def parse_any(x):
    # TODO: not supported yet
    assert False
