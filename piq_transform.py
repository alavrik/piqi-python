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


def transform_tokens_common(filename, infile):
    tokens = tokenize.generate_tokens(infile)
    return transform_token_list(filename, list(tokens))


def transform_tokens_from_string(s):
    filename = '-'
    return transform_tokens_common(filename, StringIO.StringIO(s).readline)


def transform_tokens_from_file(filename):
    with open(filename, 'rb') as infile:
        return transform_tokens_common(filename, infile.readline)


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




def transform_ast(filename):
    tokens = transform_tokens_from_file(filename)
    source = tokenize.untokenize(tokens)
    source_ast = ast.parse(source, filename, 'exec')
    return AstExprWrapper().visit(source_ast)


def exec_file(filename, user_globals=None):
    source_ast = transform_ast(filename)

    if user_globals is not None:
        exec_globals = user_globals
    else:
        exec_globals = {}

    exec_globals.update(dict(
        _piq_wrap_object = wrap_object,
        _piq_make_name = make_name,
        _piq_make_named = make_named,
        _piq_make_splice = make_splice
    ))

    exec(compile(source_ast, filename, 'exec'), exec_globals)


def main():
    arg_transform_tokens = False
    arg_transform_ast = False
    arg_tokenize = False

    args = sys.argv[1:]

    i = 0
    while True:
        if i >= len(args):
            break

        a = args[i]

        if a in ['-t', '--tokenize']:
            arg_tokenize = True
        elif a in ['-tt', '--transform-tokens']:
            arg_transform_tokens = True
        elif a in ['-ta', '--transform-ast']:
            arg_transform_ast = True
        elif a.startswith('-'):
            pass
        else:
            break  # positional argument
        i += 1

    positional_arg = args[i]
    filename = positional_arg

    if arg_tokenize:
        out_tokens = transform_tokens_from_file(filename)

        res = []
        for token in out_tokens:
            res.append((pytoken.tok_name[token[0]], token[1]))

        print res
    elif arg_transform_tokens:
        out_tokens = transform_tokens_from_file(filename)
        source = tokenize.untokenize(out_tokens)
        print source
    elif arg_transform_ast:
        source_ast = transform_ast(filename)
        #print ast.dump(source_ast)
        #import astunparse
        #print astunparse.unparse(source_ast)
        #import astor
        #print astor.to_source(source_ast)
        print source_ast
    else:
        # XXX
        try:
            exec_file(filename)
        except piq.ParseError as e:
            sys.stderr.write(filename + ':' + str(loc.line) + ': ' + error)
            sys.exit(1)


if __name__ == '__main__':
    main()
