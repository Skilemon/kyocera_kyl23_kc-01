#!/bin/sh
#
# Pack the extracted proprietary files into the tarball the workflow downloads.
#
# The blobs are release assets rather than git contents: 74 MB of binaries
# would be cloned by everyone who only wants the device tree, and they are
# Kyocera's and Qualcomm's code, not ours to redistribute in a source repo.
#
# Usage:
#   tools/blobs/pack.sh [output.tar.gz]
#
# Expected layout inside the archive (relative to vendor/kyocera/msm8926-common):
#   proprietary/vendor/lib/...
#   proprietary/vendor/bin/...
#   proprietary/system/etc/...
#
# which is exactly what extract.py writes, so the workflow can untar straight
# into vendor/kyocera/msm8926-common/.
#
set -eu

repo=$(cd "$(dirname "$0")/../.." && pwd)
src="$repo/vendor/kyocera/msm8926-common/proprietary"
out=${1:-"$repo/proprietary.tar.gz"}

if [ ! -d "$src" ]; then
    echo "no proprietary tree at $src -- run tools/blobs/extract.py first" >&2
    exit 1
fi

# Deterministic archive: sorted names, no owner/mtime noise, so the checksum
# below only changes when a file actually changes.
tar --sort=name \
    --owner=0 --group=0 --numeric-owner \
    --mtime='2015-08-18 20:22:59 UTC' \
    -czf "$out" \
    -C "$repo/vendor/kyocera/msm8926-common" proprietary

printf '%s  %s\n' "$(md5sum "$out" | cut -d' ' -f1)" "$out"
printf 'files: %s  size: %s\n' \
    "$(find "$src" -type f | wc -l)" \
    "$(du -h "$out" | cut -f1)"
