#!/bin/sh
#
# build.sh -- build the two HAL libraries in this directory from source.
#
# Toolchain: arm-linux-gnueabi-gcc (Debian/Ubuntu's gcc-arm-linux-gnueabi and
#            binutils-arm-linux-gnueabi packages).
# Kernel:    the 3.4 tree this device actually runs, for <sound/asound.h> and
#            the ioctl numbers / struct layouts the phone's ALSA implements.
#
# Linkage.  Both libraries keep every libc symbol undefined and declare
# DT_NEEDED libc.so -- what bionic expects.  Linking the usual way gives
# DT_NEEDED libc.so.6 plus open64/mmap64/__ioctl_time64, none of which exist on
# the phone, and the .so dies at load time with "cannot locate symbol" before
# its first instruction runs (section 37.5).
#
# Ubuntu's gcc-arm-linux-gnueabi defaults to _TIME_BITS=64 and
# _FILE_OFFSET_BITS=64 -- that is where open64/mmap64/__ioctl_time64 come from.
# -D_TIME_BITS=32 -D_FILE_OFFSET_BITS=32 restores the plain 32-bit names
# bionic actually has; fortify is off for the same reason.
#
# libtinyalsa is *unmodified upstream 7.1 tinyalsa* (pcm.c + mixer.c from
# CyanogenMod's android_external_tinyalsa, cm-14.1) built with
# -DIGNORE_SILENCE_SIZE.  That macro is upstream's own switch: it drops
# struct pcm_config's silence_size field, leaving
#
#     channels, rate, period_size, period_count, format,
#     start_threshold, stop_threshold, silence_threshold, avail_min
#
# -- 36 bytes, byte for byte the KitKat struct this device's vendor audio HAL
# was compiled against, with avail_min at offset 32.  The 40-byte 7.1 layout
# puts silence_size there, and the kernel's snd_pcm_sw_params() then compares
# 240 (the old avail_min) against a zero silence_threshold and returns EINVAL
# (sound/core/pcm_native.c:541).  That alone made every pcm_open fail with
# "cannot set sw params" (section 34).
#
# A caller that really does pass the 40-byte struct (the 7.1 usb HAL) leaves
# avail_min at offset 36, so this build reads its silence_size -- 0 -- and
# upstream's own fallback turns that into period_size.  One library, both
# layouts, no ABI guessing.
#
# stub/libc.so is a bionic libc stub, used only to give the link a symbol
# provider and a soname; its code never ships.
set -e
cd "$(dirname "$0")"

KERNEL=${KERNEL:-/workspace/source/kernel}
STUB=${STUB:-$PWD/stub}
CC=${CC:-arm-linux-gnueabi-gcc}
OUT=${OUT:-../lib}

ABI="-D_TIME_BITS=32 -D_FILE_OFFSET_BITS=32 -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=0"
CFLAGS="-shared -fPIC -O2 -fno-stack-protector -nostdlib $ABI"
LDFLAGS="-Wl,-rpath-link,$STUB -L$STUB -l:libc.so"

$CC $CFLAGS -DKC_TARGET_BIONIC -DIGNORE_SILENCE_SIZE \
    -Itinyalsa/include -I"$KERNEL/include" -I"$KERNEL/arch/arm/include" \
    -o "$OUT/libtinyalsa.so" tinyalsa/pcm.c tinyalsa/mixer.c \
    -Wl,-soname,libtinyalsa.so $LDFLAGS -lgcc

$CC $CFLAGS \
    -o "$OUT/lights.default.so" lights7.c \
    -Wl,-soname,lights.default.so $LDFLAGS

echo "--- built ---"
ls -l "$OUT/libtinyalsa.so" "$OUT/lights.default.so"
echo "--- dynamic deps (must be libc.so, never libc.so.6) ---"
readelf -d "$OUT/libtinyalsa.so" | grep NEEDED
readelf -d "$OUT/lights.default.so" | grep NEEDED
echo "--- undefined (must all exist in bionic) ---"
readelf -sW "$OUT/libtinyalsa.so" | awk '$7=="UND"{print $8}' | sed 's/@.*//' | sort -u | tr '\n' ' '; echo
echo "--- pcm_config size check (must be 36) ---"
printf '#include <stdio.h>\n#include <tinyalsa/asoundlib.h>\nint main(void){printf("sizeof(struct pcm_config)=%%zu\\n",sizeof(struct pcm_config));return 0;}\n' > /tmp/kc_cfgchk.c
${HOSTCC:-gcc} -DIGNORE_SILENCE_SIZE -Itinyalsa/include -o /tmp/kc_cfgchk /tmp/kc_cfgchk.c && /tmp/kc_cfgchk

# ---------------------------------------------------------------------------
# kcprox -- the pocket-mode daemon (see kcprox.c for why it exists).
#
# Static, and deliberately not built like the two HAL libraries above: this one
# is a program, not a library that bionic loads, so it carries its own libc and
# the "which symbols does bionic have" problem does not apply.  What does apply
# is the Ubuntu toolchain's default to _TIME_BITS=64: glibc then routes
# clock_gettime() to the __clock_gettime64 syscall (403), which a 3.4 kernel
# does not have, and every timestamp in the log would come out of an
# uninitialised struct.  -D_TIME_BITS=32 keeps the 32-bit entry points.
#
# kcbtnled (fix24) was the first static ARM binary on this device, so the shape
# is known to run: bionic's linker is not involved at all.
OUT=${OUT:-../bin}
$CC -static -O2 -D_TIME_BITS=32 -D_FILE_OFFSET_BITS=32 \
    -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=0 \
    -o "$OUT/kcprox" kcprox.c
arm-linux-gnueabi-strip "$OUT/kcprox" 2>/dev/null || true
echo "--- built ---"
ls -l "$OUT/kcprox"
file "$OUT/kcprox"
