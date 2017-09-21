#!/usr/bin/env python
#
# TODO
#
# - more restrictive parsing -- allow transform only inside [ ... ] or single ()

import sys
import StringIO

import tokenize
import token as pytoken
import keyword as pykeyword
import ast

import piq


def is_token(l, i, toknum, tokval=None):
    if i >= len(l):
        return False

    token = l[i]
    if toknum == token[0]:
        if tokval == None:
            return True
        else:
            return (tokval == token[1])
    else:
        return False


def is_token_op(l, i, opname=None):
    return is_token(l, i, pytoken.OP, tokval=opname)


def is_token_op_in(l, i, opnames):
    for opname in opnames:
        if is_token_op(l, i, opname):
            return True
    return False


def is_token_name(l, i):
    return is_token(l, i, pytoken.NAME)


def peek_token(l, i):
    if i >= len(l):
        return None
    else:
        return l[i]


def pop_token(l, i):
    return (l[i], i + 1)


def is_token_keyword(l, i):
    token = peek_token(l, i)
    return (token is not None and token[0] == pytoken.NAME and pykeyword.iskeyword(token[1]))


def is_token_op_value_start(l, i):
    return is_token_op_in(l, i, ['`', '(', '[', '{', '-', '+', '~'])


def is_token_value_start(l, i):
    return (not is_token_op(l, i) or is_token_op_value_start(l, i)) and not is_token_keyword(l, i) and not is_token(l, i, pytoken.ENDMARKER)


def make_token(toknum, tokval, tokstart = None, tokend = None):
    if tokstart is None:
        return (toknum, tokval)
    else:
        if tokend is None:
            tokend = tokstart
        return (toknum, tokval, tokstart, tokend, None)


def is_piq_name_start(l, i):
    return is_token_op(l, i, '.') and is_token_name(l, i + 1)


def is_piq_name_continue(l, i):
    return is_token_op(l, i, '-') and is_token_name(l, i + 1)


# skip insignificant tokens
def skip_nl_and_comment_tokens(l, i, accu):
    if is_token(l, i, tokenize.NL) or is_token(l, i, tokenize.COMMENT):
        token, i = pop_token(l, i)
        accu.append(token)
        return skip_nl_and_comment_tokens(l, i, accu)  # see if we've got more of these
    else:
        return i


def transform_piq_name(filename, l, i, accu, name=None, name_loc=None):
    # '.' in case of name start, '-' in case of another name segment
    #
    # TODO: make sure '-' immediately follow preceeding name segment
    dot_or_dash_token, i = pop_token(l, i)
    dot_loc = dot_or_dash_token[3]
    dot_or_dash = dot_or_dash_token[1]

    name_token, i = pop_token(l, i)
    name_token_val = name_token[1]

    if name is None:
        name = ''
    else:
        name += dot_or_dash
    name += name_token_val

    if name_loc is None:
        name_loc = dot_loc

    def accu_append_keyword(keyword):
        def make_loc(loc):
            return [
                (pytoken.OP, ','),
                (pytoken.OP, '('),
                #(pytoken.STRING, "'" + filename + "'"),
                #(pytoken.OP, ','),
                (pytoken.NUMBER, str(loc[0])),  # line
                (pytoken.OP, ','),
                (pytoken.NUMBER, str(loc[1])),  # column
                (pytoken.OP, ')')
            ]

        accu.extend([
            (pytoken.NAME, keyword),
            (pytoken.OP, '('),
            (pytoken.STRING, "'" + name + "'")
        ])

        accu.extend(make_loc(name_loc))

        accu.extend([
            (pytoken.OP, ')')
        ])

    if is_piq_name_start(l, i):
        # next token is also a name => this name is chained with another Piq
        # name => recurse
        i = transform_piq_name(filename, l, i, accu, name, name_loc)
    elif is_piq_name_continue(l, i):
        # next token is a '-' followed by another name segment => recurse
        i = transform_piq_name(filename, l, i, accu, name, name_loc)
    else:
        # something else

        # skip whitespace
        nl_and_comment_accu = []
        i = skip_nl_and_comment_tokens(l, i, nl_and_comment_accu)

        if is_token_op_in(l, i, [')', ']', ',']):
            # end of name
            accu_append_keyword('_piq_make_name')
        elif is_token_value_start(l, i):
            # value juxtaposition
            accu_append_keyword('_piq_make_named')

            accu.append((pytoken.OP, '**'))
        elif is_token_op(l, i, '*') and is_token_value_start(l, i + 1):
            # splice
            accu_append_keyword('_piq_make_splice')

            # replace '*' with '**' which has a higher precedence and stronger
            # binding
            _, i = pop_token(l, i)
            accu.append((pytoken.OP, '**'))
        else:
            # something else, likely an error
            error_tok =  peek_token(l, i)
            error_tok_loc = error_tok[3]

            loc = piq.make_loc((error_tok_loc[0], error_tok_loc[1]))
            raise piq.ParseError(loc, "label must be followed by value, '*' value, or one of ')', ']', ','")

        # insert back newlines and comments
        accu.extend(nl_and_comment_accu)

    return i


def transform_token_list(filename, l):
    accu = []
    i = 0

    i = skip_nl_and_comment_tokens(l, i, accu)

    piq_name_allowed = False
    while True:
        if i >= len(l):
            return accu

        if piq_name_allowed and is_piq_name_start(l, i):
            i = transform_piq_name(filename, l, i, accu)

            # Piq name can not be immediately followed by another Piq name
            piq_name_allowed = False
        else:
            # Piq name is allowed only after these tokens
            #
            # TODO: allow only commas inside lists
            piq_name_allowed = is_token_op_in(l, i, ['(', '[', ','])

            token, i = pop_token(l, i)
            accu.append(token)

            i = skip_nl_and_comment_tokens(l, i, accu)


def tokenize_common(infile):
    tokens = tokenize.generate_tokens(infile)
    return list(tokens)


def tokenize_string(s):
    return tokenize_common(StringIO.StringIO(s).readline)


def tokenize_file(filename):
    with open(filename, 'rb') as infile:
        return tokenize_common(infile.readline)


def tokenize_and_transform_string(s, filename='-'):
    tokens = tokenize_string(s)
    return transform_token_list(filename, tokens)


def tokenize_and_transform_file(filename):
    tokens = tokenize_file(filename)
    return transform_token_list(filename, tokens)


class AstExprWrapper(ast.NodeTransformer):
    """Wraps all (load) expressions in a call to piq.ObjectProxy()"""
    def visit(self, node):
        node = self.generic_visit(node)
        ctx = getattr(node, 'ctx', None)
        if isinstance(node, ast.expr) and (not ctx or isinstance(ctx, ast.Load)):
            # TODO, XXX: don't wrap Call.func, because it can never result in a
            # piq data structure, also won't need __call__ method in
            # piq.ObjectProxy()

            # TODO: transform (_piq_make_named(name, loc) ** value) into
            # Named(name, loc, value); similarly, for _piq_make_splice()
            #
            # this way, we won't need AbstractNamed and AbstractSplice runtime

            #print "NODE:", node, list(ast.iter_fields(node))

            def make_node(new_node):
                return ast.copy_location(new_node, node)

            lineno = make_node(ast.Num(node.lineno))
            col_offset = make_node(ast.Num(node.col_offset))
            func = make_node(ast.Name(id='_piq_wrap_object', ctx=ast.Load()))

            return make_node(ast.Call(
                func=func,
                args=[node, lineno, col_offset],
                keywords=[]
            ))
        else:
            return node


class AstOverrideOperators(ast.NodeTransformer):
    """Wraps all (load) expressions in a call to piq.ObjectProxy()"""
    def visit(self, node):
        node = self.generic_visit(node)

        def make_node(new_node):
            return ast.copy_location(new_node, node)

        def make_operator_node(name, args):
            func = make_node(ast.Name(id='_piq_operator_' + name, ctx=ast.Load()))

            return make_node(ast.Call(
                func=func,
                args=args,
                keywords=[]
            ))

        def make_lazy_bool_operator_node(name, args):
            def make_lazy_arg_node(body):
                args = make_node(ast.arguments(
                    args=[],
                    vararg=None,
                    kwarg=None,
                    defaults=[]
                ))
                return make_node(ast.Lambda(
                    args=args,
                    body=body
                ))

            lazy_arg_nodes = [make_lazy_arg_node(x) for x in args]

            return make_operator_node(name, lazy_arg_nodes)

        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
            return make_lazy_bool_operator_node('and', node.values)

        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            return make_lazy_bool_operator_node('or', node.values)

        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return make_operator_node('not', [node.operand])

        elif isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], (ast.In, ast.NotIn)):
            # NOTE, XXX: not handling chained comparison operators, for example:
            #
            #    1 in 2 in 3
            #    1 in 2 > 3
            #    1 in 2 not in 3

            in_node = make_operator_node('in', [node.left, node.comparators[0]])

            if isinstance(node.ops[0], ast.In):
                return in_node
            else:
                return make_operator_node('not', [in_node])

        else:
            return node


class AbstractNamed(object):
    def __init__(self, name, loc):
        self.name = name
        self.loc = loc

    def __pow__(self, other):
        return piq.Named(self.name, self.loc, other)


class AbstractSplice(AbstractNamed):
    def __pow__(self, other):
        return piq.Splice(self.name, self.loc, other)


def wrap_object(*args):
    return piq.wrap_object(*args)
def make_name(name, loc):
    return piq.Name(name, loc)
def make_named(name, loc):
    return AbstractNamed(name, loc)
def make_splice(name, loc):
    return AbstractSplice(name, loc)

# default implementation for overridden boolean operators
def operator_and(*args):
    for x in args:
        if not x(): return False
    return True

def operator_or(*args):
    for x in args:
        if x(): return True
    return False

def operator_not(arg):
    return (not arg)

def operator_in(left, right):
    return (left in right)


# this is tweaked version of tokenize.Untokenizer.compact()
#
def untokenize(tokens):
    # stock Python's tokenize.untokenize() has a bug/omission when it doesn't
    # correctly carry indent state upon switching from Untokenizer.untokenize()
    # to Untokenizer.compat()
    #
    # to make it happy, we are forcing it to switch to Untokenizer.compat() on
    # the first token
    first_token = tokens[0]
    tokens[0] = (first_token[0], first_token[1])

    return tokenize.untokenize(tokens)


def parse_file(filename):
    tokens = tokenize_and_transform_file(filename)
    source = untokenize(tokens)
    return ast.parse(source, filename, 'exec')


# for AST transformations see
#
# https://docs.python.org/3/library/ast.html
# https://docs.python.org/2/library/ast.html
# http://greentreesnakes.readthedocs.io/

def parse_and_transform_file(filename, transform_expressions=True, transform_operators=True):
    ast = parse_file(filename)

    if transform_expressions:
        ast = AstExprWrapper().visit(ast)

    if transform_operators:
        ast = AstOverrideOperators().visit(ast)

    return ast


def exec_file(filename, user_globals=None, transform_operators=False):
    transformed_ast = parse_and_transform_file(filename, transform_operators=transform_operators)

    if user_globals is not None:
        assert isinstance(user_globals, dict)
        exec_globals = user_globals
    else:
        exec_globals = {}

    exec_globals.update(dict(
        _piq_wrap_object = wrap_object,
        _piq_make_name = make_name,
        _piq_make_named = make_named,
        _piq_make_splice = make_splice
    ))

    if transform_operators:
        exec_globals.setdefault('_piq_operator_and', operator_and)
        exec_globals.setdefault('_piq_operator_or', operator_or)
        exec_globals.setdefault('_piq_operator_not', operator_not)
        exec_globals.setdefault('_piq_operator_in', operator_in)

    exec(compile(transformed_ast, filename, 'exec'), exec_globals)


def main():
    arg_tokenize = False
    arg_tokenize_transform = False
    arg_parse = False

    arg_parse_transform = False
    arg_transform_operators = False
    arg_transform_expressions = False

    arg_abstract_output = False


    args = sys.argv[1:]

    i = 0
    while True:
        if i >= len(args):
            break

        a = args[i]

        if a in ['-t', '--tokenize']:
            arg_tokenize = True
            arg_abstract_output = True
        elif a in ['-tt', '--tokenize-transform']:
            arg_tokenize_transform = True
        elif a in ['-p', '--parse']:
            arg_parse = True
            arg_abstract_output = True
        elif a in ['-pt', '--parse-transform']:
            arg_parse_transform = True
            arg_transform_expressions = True
            arg_transform_operators = True
        elif a in ['-pte', '--parse-transform-expressions']:
            arg_parse_transform = True
            arg_transform_expressions = True
        elif a in ['-pto', '--parse-transform-operators']:
            arg_parse_transform = True
            arg_transform_operators = True
        elif a in ['-a', '--abstract-output']:
            arg_abstract_output = True
        elif a.startswith('-'):
            pass
        else:
            break  # positional argument
        i += 1

    positional_arg = args[i]
    filename = positional_arg

    def print_tokens(tokens):
        if arg_abstract_output:
            res = []
            for token in tokens:
                res.append((pytoken.tok_name[token[0]], token[1]))
            print res
        else:
            print untokenize(tokens)

    def print_ast(output_ast):
        if arg_abstract_output:
            try:
                import astunparse
                print astunparse.dump(output_ast)
            except ImportError:
                print ast.dump(output_ast)
        else:
            try:
                import astunparse
                print astunparse.unparse(output_ast)
            except ImportError:
                sys.exit("couldn't import 'astunparse'")

    if arg_tokenize:
        tokens = tokenize_file(filename)
        print_tokens(tokens)
    elif arg_tokenize_transform:
        tokens = tokenize_and_transform_file(filename)
        print_tokens(tokens)
    elif arg_parse:
        source_ast = parse_file(filename)
        print_ast(source_ast)
    elif arg_parse_transform:
        transformed_ast = parse_and_transform_file(
                filename,
                transform_operators=arg_transform_operators,
                transform_expressions=arg_transform_expressions)
        print_ast(transformed_ast)
    else:
        # XXX
        try:
            exec_file(filename, transform_operators=True)
        except piq.ParseError as e:
            sys.stderr.write(filename + ':' + str(loc.line) + ': ' + error)
            sys.exit(1)


if __name__ == '__main__':
    main()
