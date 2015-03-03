#! /usr/bin/env python
#
"""
A preprocessor using Jinja2 syntax.
"""
__docformat__ = 'reStructuredText'


import argparse
import os
import sys

import jinja2


## aux functions

def make_load_path(paths):
    """
    Return a list of filesystem paths, given a colon-separated list of strings.

    Examples::

      >>> make_load_path(['/tmp/a'])
      ['/tmp/a']
      >>> make_load_path(['/tmp/a:/tmp/b'])
      ['/tmp/a', '/tmp/b']
      >>> make_load_path(['/tmp/a:/tmp/b', '/tmp/c'])
      ['/tmp/a', '/tmp/b', '/tmp/c']
    """
    result = []
    for path in paths:
        result += path.split(':')
    return result


def split_dot_or_dict_syntax(expr):
    """
    Split a dotted or []-lookup expression into a series of components.

    Examples::

      >>> split_dot_or_dict_syntax('a.b.c')
      ['a', 'b', 'c']
      >>> split_dot_or_dict_syntax('a.b[c]')
      ['a', 'b', 'c']
      >>> split_dot_or_dict_syntax('a[b].c')
      ['a', 'b', 'c']

    """
    result = []
    cur = ''
    nested = 0
    for ch in expr:
        if '.' == ch:
            if cur:
                result.append(cur)
                cur = ''
        elif '[' == ch:
            nested += 1
            if cur:
                result.append(cur)
                cur = ''
        elif ']' == ch:
            nested -= 1
            if cur:
                result.append(cur)
                cur = ''
        else:
            cur += ch
    if cur:
        result.append(cur)
    return result


def parse_defines(defs, default=1):
    """
    Parse a list of variable assignments into a Python dictionary.

    Argument `defs` must be a sequence, each element of which has the
    form ``K=V``. At the basic level, this just sets key ``K`` to
    value ``V`` in the result::

      >>> D = parse_defines(['a=foo', 'b=bar'])
      >>> D['a']
      'foo'
      >>> D['b']
      'bar'

    Note that only the first equal sign ``=`` has any significance;
    any further equal signs are just taken to be part of the value::

      >>> D = parse_defines(['a=foo', 'e=bar=1'])
      >>> D['e']
      'bar=1'

    Also note that keys and values are *always* of type string::

      >>> D = parse_defines(['a=foo', 'b=bar', 'c=1'])
      >>> D['c']
      '1'

    Things get more interesting when the key part ``K`` contains a dot
    or a part enclosed in square brackets.  Then the key is split into
    components at each dot or ``[]`` expression, and nested
    dictionaries are created to contain the keys and the final value::

      >>> D = parse_defines(['sys.ipv4[lo]=127.0.0.1'])
      >>> D['sys']['ipv4']['lo']
      '127.0.0.1'
      >>> D['sys'].keys()
      ['ipv4']
      >>> D['sys']['ipv4'].keys()
      ['lo']

      >>> D = parse_defines(['sys.ipv4[lo]=127.0.0.1',
      ...                    'sys.ipv4[docker0]=192.168.0.1' ])
      >>> D['sys']['ipv4'].keys()
      ['lo', 'docker0']
      >>> D['sys']['ipv4']['lo']
      '127.0.0.1'
      >>> D['sys']['ipv4']['docker0']
      '192.168.0.1'

    """
    result = {}
    for kv in defs:
        if '=' in kv:
            k, v = kv.split('=', 1)
        else:
            k = kv
            v = default
        ks = split_dot_or_dict_syntax(k)
        if len(ks) == 1:
            # shortcut
            result[k] = v
        else:
            # create nested dictionaries as needed
            head, tail = ks[:-1], ks[-1]
            target = result
            # enumerate is only useful to generate an error msg in the
            # assertion below
            for n, h in enumerate(head):
                if h not in target:
                    target[h] = {}
                target = target[h]
                assert type(target) == dict, (
                    "Trying to assign to '%s', but '%s' is already taken"
                    " and has value %r"
                    % (k, str.join('.', ks[:n+1]), target)
                )

            target[tail] = v
    return result


## main

cmdline = argparse.ArgumentParser()
cmdline.add_argument(
    "--selftest", action='store_true', default=False,
    help="Run self-test routine and exit."
)
cmdline.add_argument(
    "-D", "--define", action='append', metavar='VAR[=VALUE]',
    help=(
        "Substitute VALUE for VAR in the input template."
        " If VALUE is not given, assume `1`."
    )
)
cmdline.add_argument(
    "-I", "--search", action='append', metavar='DIR',
    help="Search for referenced templates in the given DIR."
)
cmdline.add_argument(
    "-i", "--input", type=str, metavar='FILE', default=None,
    help=(
        "Read input template from FILE."
        " If omitted, the input template is read from STDIN."
    )
)
cmdline.add_argument(
    "-o", "--output", type=str, metavar='FILE', default=None,
    help=(
        "Write output to FILE."
        " If omitted, output is written to STDOUT."
    )
)
args = cmdline.parse_args()

# if asked, run self tests and exit
if args.selftest:
    import doctest
    fail, tested = doctest.testmod(
        name="j2pp",
        optionflags=doctest.NORMALIZE_WHITESPACE)
    sys.exit(1 if fail > 0 else 0)

# create Jinja2 template engine
if args.search:
    search_path = make_load_path(args.search)
else:
    search_path = []
loader = jinja2.FileSystemLoader(search_path)
env = jinja2.Environment(loader=loader)

# select input template
if args.input:
    with open(args.input, 'r') as source:
        template = env.from_string(source.read())
else:
    template = env.from_string(sys.stdin.read())

# select output stream
if args.output:
    output = open(args.output, 'w')
else:
    output = sys.stdout

# actually render template
kv = parse_defines(args.define)
print ("DEBUG: kv=%r" % kv)
output.write(template.render(**kv))
