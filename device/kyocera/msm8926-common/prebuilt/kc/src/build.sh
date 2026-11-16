#!/bin/sh
#
# build.sh -- build the two HAL libraries in this directory from source.
#
# Toolchain: arm-linux-gnueabi-gcc (Debian/Ubuntu's binutils-arm-linux-gnueabi
# and gcc-arm-linux-gnueabi packages).
# Kernel:    the 3.4 tree this device actually runs, for <sound/asound.h>.  Not
#            a distro's headers -- the ioctl numbers and struct layouts have to
#            be the ones the phone's ALSA stack implements.
#
# The -nostdlib + -l:libc.so pairing is deliberate.  Both libraries keep every
# libc symbol undefined and declare DT_NEEDED libc.so, which is exactly how
# bionic expects to resolve them at load time.  Compiling them the normal way
# would link them against glibc, and a 32-bit glibc emits
#
#     DT_NEEDED libc.so.6
#     open64, mmap64, __ioctl_time64
#
# none of which exist on the phone -- the .so would fail to load with "cannot
# locate symbol" before a single line of it ran.  That is what happened to the
# first hand-built lights HAL (section 37.5).
#
# stub/libc.so is a bionic libc stub, used only to give the link a symbol
# provider and a soname; its code never ships.
set -e
cd "$(dirname "$0")"

KERNEL=${KERNEL:-/workspace/source/kernel}
STUB=${STUB:-$PWD/stub}
CC=${CC:-arm-linux-gnueabi-gcc}
OUT=${OUT:-../lib}

CFLAGS="-shared -fPIC -O2 -fno-stack-protector -nostdlib"
LDFLAGS="-Wl,-rpath-link,$STUB -L$STUB -l:libc.so"

$CC $CFLAGS -fvisibility=hidden \
    -I"$KERNEL/include" -I"$KERNEL/arch/arm/include" \
    -o "$OUT/libtinyalsa.so" tinyalsa7.c \
    -Wl,-soname,libtinyalsa.so $LDFLAGS -lgcc

$CC $CFLAGS \
    -o "$OUT/lights.default.so" lights7.c \
    -Wl,-soname,lights.default.so $LDFLAGS

echo "--- built ---"
ls -l "$OUT/libtinyalsa.so" "$OUT/lights.default.so"
echo "--- dynamic deps (must be libc.so, never libc.so.6) ---"
readelf -d "$OUT/libtinyalsa.so" | grep NEEDED
readelf -d "$OUT/lights.default.so" | grep NEEDED
