#! /usr/bin/env python
#
"""
A preprocessor using Jinja2 syntax.
"""
__docformat__ = 'reStructuredText'


import argparse
import logging
import os
import sys

import jinja2


logging.basicConfig(
    format="%(module)s: %(levelname)s: %(message)s",
    level=logging.WARNING)


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

    Only outermost brackets are taken as a dict-style lookup
    expression; any string appearing within the outermost pair of
    brackets is taken as a single component (including dots and other
    brackets!).

    ::

      >>> split_dot_or_dict_syntax('a[b[1]].c')
      ['a', 'b[1]', 'c']
      >>> split_dot_or_dict_syntax('a.b[c[1].d].e')
      ['a', 'b', 'c[1].d', 'e']

    Note that (as a consequence of the above), brackets must be
    balanced, i.e., any open bracket must have a matching close one;
    otherwise, an `AssertionError` is raised::

      >>> split_dot_or_dict_syntax('a[b[1].c')
      Traceback (most recent call last):
        ...
      AssertionError

    """
    result = []
    cur = ''
    nested = 0
    for ch in expr:
        if '.' == ch:
            if nested != 0:
                cur += ch
            else:
                if cur:
                    result.append(cur)
                    cur = ''
        elif '[' == ch:
            if nested != 0:
                cur += ch
            else:
                if cur:
                    result.append(cur)
                    cur = ''
            nested += 1
        elif ']' == ch:
            nested -= 1
            if nested != 0:
                cur += ch
            else:
                if cur:
                    result.append(cur)
                    cur = ''
        else:
            cur += ch
    assert nested == 0
    if cur:
        result.append(cur)
    return result


def _add(target, key, val):
    """
    Add `val` to the list of values of `key` in `target`.

    However, if `key` does not exist in `target` (i.e., we are adding
    the first value ever), then `key` is set to `value`.  In other
    words, the change to a list happens when adding a second value.

    This is a helper function for `parse_defines`.
    """
    if key in target:
        if type(target[key]) != list:
            target[key] = [target[key]]
        target[key].append(val)
    else:
        target[key] = val


def parse_defines(defs, default=1,
                  lengthen=True, shorten=False,
                  logger=logging):
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

    There's one exception, though: if the ``=value`` part is omitted,
    a key is assigned the value given by the `default` argument
    *without conversion* ::

      >>> D = parse_defines(['a'])
      >>> D['a']
      1
      >>> type(D['a'])
      <type 'int'>
      >>> D = parse_defines(['a'], default=True)
      >>> D['a']
      True

    The same key may appear multiple times: values are then
    concatenated into a list. (Similarly to what CGI modules do with
    query strings.)  An example might clarify::

      >>> D = parse_defines(['a=1', 'a=2', 'a=3'])
      >>> D['a']
      ['1', '2', '3']

    Things get more interesting when the key part ``K`` contains a dot
    or a part enclosed in square brackets.  Then the key is split into
    components at each dot or ``[]`` expression (see
    :func:`split_dot_or_dict_syntax`), and nested dictionaries are
    created to contain the keys and the final value::

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

    Now, it is possible that a composite key commands the creation of
    nested dictionaries (i.e., extend the tree) where a scalar string
    value is already present.  Optional third argument `lenghten`
    controls the bahavior in this case:

    - if `lenghten` is ``True`` (default), then later assignments to
      longer composite keys overwrite previosuly-assigned scalar
      values::

      >>> D = parse_defines(['sys.ipv4=127.0.0.1',
      ...                    'sys.ipv4[docker0]=192.168.0.1' ])
      >>> D['sys']['ipv4']
      {'docker0': '192.168.0.1'}

    - if `lengthen` is ``False``, the scalar string value is kept
      and the later assignment is discarded::

      >>> D = parse_defines(['sys.ipv4=127.0.0.1',
      ...                    'sys.ipv4[docker0]=192.168.0.1' ],
      ...                    lengthen=False)
      >>> D['sys']['ipv4']
      '127.0.0.1'

    Similarly, optional fouth argument `shorten` controls what happens
    when a composite key assigns a scalar value to an existing branch
    in the dict tree:

    - if `shorten` is ``False`` (default), then later assignments to a
      shorter composite key are ignored, i.e., the existing tree branch
      is kept::

      >>> D = parse_defines(['sys.ipv4[docker0]=192.168.0.1',
      ...                    'sys.ipv4=127.0.0.1'])
      >>> D['sys']['ipv4']
      {'docker0': '192.168.0.1'}

    - if `shorten` is ``True``, then later assignments to a shorter
      composite key prune the existing tree and overwrite the branch
      with a single scalar value::

      >>> D = parse_defines(['sys.ipv4[docker0]=192.168.0.1',
      ...                    'sys.ipv4=127.0.0.1'],
      ...                   shorten=True)
      >>> D['sys']['ipv4']
      '127.0.0.1'
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
            _add(result, k, v)
        else:
            # create nested dictionaries as needed
            head, tail = ks[:-1], ks[-1]
            target = result
            ok = True
            # enumerate is only useful to generate a sensible msg in
            # the warnings below
            for n, h in enumerate(head):
                if h not in target:
                    target[h] = {}
                if type(target[h]) != dict:
                    if lengthen:
                        if logger:
                            logger.warning(
                                "Assignment to key '%s' overwrites existing key/value '%s=%r'",
                                k, str.join('.', ks[:n+1]), target[h])
                        target[h] = {}
                    else:
                        if logger:
                            logger.warning(
                                "Assignment to key '%s' ignored:"
                                " key '%s' already exists with value %r",
                                k, str.join('.', ks[:n+1]), target[h])
                        ok = False # skip assignment below
                        break
                target = target[h]
            if ok:
                if tail in target and type(target[tail]) == dict:
                    if shorten:
                        if logger:
                            logger.warning(
                                "Assignment of value %r to key '%s'"
                                " prunes existing key tree.",
                                v, k)
                        target[tail] = v
                    else:
                        if logger:
                            logger.warning(
                                "Ignoring assignment of value %r to key '%s'"
                                " as it would prune existing key tree.",
                                v, k)
                else:
                    _add(target, tail, v)

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
output.write(template.render(**kv))
