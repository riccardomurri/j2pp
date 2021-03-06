#! /usr/bin/env python
#
"""
A text file preprocessor using Jinja2 syntax: execute Jinja2
directives in the INPUT file, and write the result to the OUTPUT file.

Data to be substituted into the template is defined using the `-D
NAME=VALUE` option (see below).  Dots and "subscript" ([]) syntax is
correctly interpreted in the NAME part: i.e., given `-D NAME=VALUE`
you can refer to NAME in the input Jinja2 template to get back VALUE.
Lists are defined by repeated assignment to the same NAME: `-DNAME=1
-DNAME=2 -DNAME=3` will define `NAME` as the Jinja2 list `[1,2,3]`.
"""
##
# Copyright (C) 2015 S3IT, Zentrale Informatik, University of Zurich.
# All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/#GPL>.
##
__docformat__ = 'reStructuredText'
__author__ = 'Riccardo Murri <riccardo.murri@uzh.ch>'
__version__ = '1.0'


import argparse
import logging
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


def _add(target, key, val, logger):
    """
    Add `val` to the list of values of `key` in `target`.

    However, if `key` does not exist in `target` (i.e., we are adding
    the first value ever), then `key` is set to `value`.  In other
    words, the change to a list happens when adding a second value.

    This is a helper function for `parse_defines`.
    """
    if key in target:
        if type(target[key]) != list:
            logger.debug("Converting leaf key '%s' to list type", key)
            target[key] = [target[key]]
            logger.debug("Added value %r to leaf key '%s'.", key, val)
        target[key].append(val)
    else:
        target[key] = val
        logger.debug("Leaf key '%s' set to value %r.", key, val)


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
        logging.debug("Setting key '%s' to value %r ...", str.join('.', ks), v)
        if len(ks) == 1:
            # shortcut
            _add(result, k, v, logger)
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
                                "Assignment to key '%s' overwrites existing key/value '%s=%s'",
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
                    _add(target, tail, v, logger)

    return result


## main

cmdline = argparse.ArgumentParser(
    description=__doc__,
    formatter_class=argparse.RawDescriptionHelpFormatter,
)
cmdline.add_argument(
    "-V", "--version", action='store_true', default=False,
    help="Show program name and version and exit."
)
cmdline.add_argument(
    "--selftest", action='store_true', default=False,
    help="Run self-test routine and exit."
)
cmdline.add_argument(
    "-v", "--verbose", action='count', default=0,
    help=(
        "Log program actions at increasing detail."
        " Repeat thrice or more for debug-level info."
    )
)
cmdline.add_argument(
    "-D", "--define", action='append', metavar='NAME[=VALUE]',
    help=(
        "Substitute VALUE for NAME in the input template."
        " If VALUE is not given, assume `1`."
    )
)
cmdline.add_argument(
    "-I", "--search", action='append', metavar='DIR',
    help="Search for referenced templates in the given DIR."
)
cmdline.add_argument(
    "-i", "--input", type=str, metavar='INPUT', default=None,
    help=(
        "Read input template from file INPUT."
        " If omitted, the input template is read from STDIN."
    )
)
cmdline.add_argument(
    "-o", "--output", type=str, metavar='OUTPUT', default=None,
    help=(
        "Write output to file OUTPUT."
        " If omitted, output is written to STDOUT."
    )
)
args = cmdline.parse_args()

# if asked, print version string and exit
if args.version:
    print ("j2pp version " + __version__)
    sys.exit(0)

# if asked, run self tests and exit
if args.selftest:
    import doctest
    fail, tested = doctest.testmod(
        name="j2pp",
        optionflags=doctest.NORMALIZE_WHITESPACE)
    sys.exit(1 if fail > 0 else 0)

# make logging as verbose as requested
logging.basicConfig(
    format="%(module)s: %(levelname)s: %(message)s",
    level=logging.ERROR - 10 * args.verbose)

# create Jinja2 template engine
if args.search:
    search_path = make_load_path(args.search)
else:
    search_path = []
logging.info("Jinja template search path is: %r", search_path)
loader = jinja2.FileSystemLoader(search_path)
env = jinja2.Environment(loader=loader)

# select input template
if args.input:
    logging.info("Reading input template from file '%s' ...", args.input)
    with open(args.input, 'r') as source:
        template = env.from_string(source.read())
else:
    logging.info("Reading input template from STDIN ...")
    template = env.from_string(sys.stdin.read())

# select output stream
if args.output:
    logging.info("Writing processed output to file '%s' ...", args.output)
    output = open(args.output, 'w')
else:
    logging.info("Writing processed output to STDOUT ...")
    output = sys.stdout

# actually render template
logging.info("Parsing defines into a tree ...")
kv = parse_defines(args.define)

logging.info("Rendering Jinja2 template ...")
output.write(template.render(**kv))

logging.info("All done.")
