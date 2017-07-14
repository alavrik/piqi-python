import wrappers


class ObjectProxy(wrappers.ObjectProxy):
    def __init__(self, wrapped, loc):
        super(ObjectProxy, self).__init__(wrapped)
        self._self_loc = loc

    @property
    def __loc__(self):
	return self._self_loc

    def __call__(self, *args, **kwargs):
        return self.__wrapped__(*args, **kwargs)

    def __repr__(self):
        return repr(self.__wrapped__)


# called from modified AST
def wrap_object(x, lineno, col_offset):
    loc = make_loc((lineno, col_offset))
    return ObjectProxy(x, loc)


# remove extra wrapping upon constracting Piq AST nodes
def unwrap_object(x):
    if isinstance(x, ObjectProxy):
        return unwrap_object(x.__wrapped__)
    else:
        return x


class Loc(object):
    def __init__(self, init_loc):
        self.line, self.column = init_loc

    def __repr__(self):
        return "{}:{}".format(self.line, self.column)


def make_loc(loc):
    if loc is None:
        return None
    elif isinstance(loc, Loc):
        return loc
    else:
        return Loc(loc)


class ParseError(Exception):
    def __init__(self, loc, error):
        self.error = error
        self.loc = loc
    def __repr__(self):
        return error


def is_piq_node(x):
    return isinstance(x, (Name, Named, List, Splice, Scalar))


# make piq AST node
def make_node(x, is_inside_list=False):
    if is_piq_node(x):
        # already a Piq node
        return unwrap_object(x)
    elif isinstance(x, (bool, int, float, basestring)):
        return Scalar(unwrap_object(x), x.__loc__)
    elif isinstance(x, list):
        # XXX: support iterables?
        items = [make_node(item, is_inside_list=True) for item in x]
        return List(items, x.__loc__)
    else:
        raise ParseError(
                x.__loc__,
                "value of invalid type '{}': {}".format(type_name(x), x)
        )


def type_name(x):
    return type(unwrap_object(x)).__name__


# splice Splice'd values into the outer lists
def transform_expand_splices(node):
    if isinstance(node, List):
        new_items = []
        for item in node.items:
            if isinstance(item, Splice):
                new_items.extend(item.expand())
            else:
                new_items.append(transform_expand_splices(item))
        node.items = new_items

    return node


# value of one of the primitive Piq types
class Scalar(object):
    def __init__(self, value, loc):
        self.value = value
        self.loc = loc

    def __repr__(self):
        return repr(self.value)


# list of nodes
class List(object):
    def __init__(self, items, loc):
        self.items = items
        self.loc = loc

    def __repr__(self):
        return repr(self.items)


class Name(object):
    def __init__(self, name, loc):
        self.name = name
        self.loc = make_loc(loc)

    def __repr__(self):
        return '.' + self.name


class Named(object):
    def __init__(self, name, loc, value):
        self.name = name
        self.loc = make_loc(loc)
        self.value = make_node(value)

    def __repr__(self):
        #name_repr = repr(self.name)
        name_repr = '.' + self.name
        value_repr = repr(self.value)

        if isinstance(self.value, Name) or isinstance(self.value, Named):
            return name_repr + ' (' + value_repr + ')'
        else:
            return name_repr + ' ' + value_repr


# list of values to be spliced into the containing list
class Splice(object):
    def __init__(self, name, loc, items):
        if not isinstance(items, list):
            raise ParseError(
                    items.__loc__,
                    "{}* must be followed by a list, instead followed by a value of type '{}': {}".format(
                        self.name, type_name(items), items
                    )
            )

        self.name = name
        self.loc = make_loc(loc)
        self.items = [make_node(x) for x in items]

    def __repr__(self):
        return '.' + self.name + '* ' + repr(self.items)

    def expand(self):
        return [Named(self.name, self.loc, x) for x in self.items]


def parse(x, expand_splices=False, expand_names=False):
    node = make_node(x)

    if expand_splices:
        node = transform_expand_splices(node)

    # TODO, FIXME: expand name chains
    if expand_names:
        pass

    return node