#! /bin/sh

../j2pp.py \
    -D domain=example.org \
    -D sys.hwaddrs=11:22:33:44:55:66 \
    -D sys.hwaddrs=aa:bb:cc:dd:ee:ff \
    -D sys.ipv4[lo]=127.0.0.1 \
    -D sys.ipv4[docker0]=192.0.2.2 \
    -i TEST.in
