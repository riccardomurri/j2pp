[j2pp][0] is a command-line text preprocessor that uses
[Jinja2 syntax][1]: it reads an input file containing Jinja2
directives and outputs the result of template rendering.
The command-line syntax tries to be remiscent of well-known
UNIX text preprocessors like [cpp][2] and [m4][3].

```console
usage: j2pp.py [-h] [-V] [--selftest] [-v] [-D NAME[=VALUE]] [-I DIR]
               [-i INPUT] [-o OUTPUT]

A text file preprocessor using Jinja2 syntax: execute Jinja2
directives in the INPUT file, and write the result to the OUTPUT file.

Data to be substituted into the template is defined using the `-D
NAME=VALUE` option (see below).  Dots and "subscript" ([]) syntax is
correctly interpreted in the NAME part: i.e., given `-D NAME=VALUE`
you can refer to NAME in the input Jinja2 template to get back VALUE.
Lists are defined by repeated assignment to the same NAME: `-DNAME=1
-DNAME=2 -DNAME=3` will define `NAME` as the Jinja2 list `[1,2,3]`.

optional arguments:
  -h, --help            show this help message and exit
  -V, --version         Show program name and version and exit.
  --selftest            Run self-test routine and exit.
  -v, --verbose         Log program actions at increasing detail. Repeat
                        thrice or more for debug-level info.
  -D NAME[=VALUE], --define NAME[=VALUE]
                        Substitute VALUE for NAME in the input template. If
                        VALUE is not given, assume `1`.
  -I DIR, --search DIR  Search for referenced templates in the given DIR.
  -i INPUT, --input INPUT
                        Read input template from file INPUT. If omitted, the
                        input template is read from STDIN.
  -o OUTPUT, --output OUTPUT
                        Write output to file OUTPUT. If omitted, output is
                        written to STDOUT.
```

[0]: http://github.com/uzh/j2pp
[1]: http://jinja.pocoo.org/docs/dev/templates/
[2]: https://gcc.gnu.org/onlinedocs/cpp/Invocation.html#Invocation
[3]: https://www.gnu.org/software/m4/manual/index.html

## Example

Given this input file::
```jinja
{# file TEST.in #}
Domain name: {{domain}}

L2 addresses (list):
{% for hwaddr in sys.hwaddrs -%}
* {{ hwaddr }}
{% endfor %}

IP network interfaces:
{% for ifname, ipv4addr in sys.ipv4.iteritems() -%}
* {{ ifname }}: {{ ipv4addr }}
{% endfor %}
```
when invoked in the following way, [j2pp][0] will produce this
output::
```console
$ ./j2pp.py \
    -D domain=example.org \
    -D sys.hwaddrs=11:22:33:44:55:66 \
    -D sys.hwaddrs=aa:bb:cc:dd:ee:ff \
    -D sys.ipv4addr[lo]=127.0.0.1 \
    -D sysipv4addr[docker0]=192.0.2.2 \
    -i TEST.in

Domain name: example.org

L2 addresses (list):
* 11:22:33:44:55:66
* aa:bb:cc:dd:ee:ff


IP network interfaces:
* lo: 127.0.0.1
* docker0: 192.0.2.2
```

## Installation

Just copy the [j2pp.py][4] script anywhere in the shell's PATH.  The
[Jinja2 Python module][5] needs to be installed for it to work.

[4]: https://raw.githubusercontent.com/uzh/j2pp/master/j2pp.py
[5]: https://pypi.python.org/pypi/Jinja2
