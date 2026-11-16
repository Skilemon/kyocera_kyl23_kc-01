#!/usr/bin/env python3
"""Give libkccabi's list_* the argument order the 4.4 blobs actually use.

libkccabi.so exists to back-fill symbols that 7.1 dropped but the 4.4 vendor
blobs still import.  Four of those are the old cutils linked list, and the
order of their arguments is the one thing that changed between the releases:

    android-4.4.4_r1  libcutils/list.c

        void list_add_tail(struct listnode *head, struct listnode *item)
        {
            item->next = head;
            item->prev = head->prev;
            head->prev->next = item;
            head->prev = item;
        }

    android-7.1      cutils/list.h, now inline, parameters reversed

        static inline void list_add_tail(struct listnode *node, struct listnode *head)

The header text is identical, the ABI is not: the blob puts the list head in
r0 and the item in r1, while a 7.1-shaped implementation reads r0 as the item
and r1 as the head.  libkccabi was written against the 7.1 order, so every
call from audio.primary.msm8226.so ran with the two swapped and dereferenced
item->prev -- zero, because the item is freshly calloc'd -- at +0x380 of
libkccabi.so.  That is the SIGSEGV in tid "AudioOut_D" that restarts
audioserver every five seconds (DEVICE_NOTES 25).

The fix is to swap the two roles inside the library; the shapes are the same
length, so both functions are patched in place and nothing else moves.

libkcabi.so (one c) is the earlier build of the same shim, nothing loads it
today, and it gets the same treatment so that it cannot bite later.

Idempotent: already-patched bytes are recognised and left alone.

Usage:
    fix_kccabi_list.py device/kyocera/msm8926-common/prebuilt/kc/lib/*.so
    fix_kccabi_list.py --check <file...>      # exit 1 if a file still needs it
"""
import struct
import sys

# file offset of each function's first instruction -> expected/given bodies
LIST_ADD_TAIL_OLD = [0xE5913004, 0xE880000A, 0xE5830000, 0xE5810004, 0xE12FFF1E]
LIST_ADD_TAIL_NEW = [0xE5903004, 0xE8810009, 0xE5831000, 0xE5801004, 0xE12FFF1E]
LIST_ADD_HEAD_OLD = [0xE5913000, 0xE5803000, 0xE5801004, 0xE5830004, 0xE5810000]
LIST_ADD_HEAD_NEW = [0xE5903000, 0xE5813000, 0xE5810004, 0xE5831004, 0xE5801000]

# symbol value of list_add_tail in each build of the shim
TAIL_AT = {"libkccabi.so": 0x378, "libkcabi.so": 0x300}


def functions(name):
    tail = TAIL_AT[name]
    return ((tail, LIST_ADD_TAIL_OLD, LIST_ADD_TAIL_NEW),
            (tail + 0x14, LIST_ADD_HEAD_OLD, LIST_ADD_HEAD_NEW))


def main(argv):
    check = "--check" in argv
    paths = [a for a in argv if not a.startswith("-")]
    if not paths:
        print(__doc__.strip().splitlines()[-1])
        return 2

    bad = 0
    for path in paths:
        name = path.rsplit("/", 1)[-1]
        if name not in TAIL_AT:
            continue
        data = bytearray(open(path, "rb").read())
        changed = []
        for off, old, new in functions(name):
            have = list(struct.unpack_from("<5I", data, off))
            if have == new:
                continue
            if have != old:
                print("%s: unexpected bytes at 0x%x: %s"
                      % (path, off, " ".join("%08x" % w for w in have)))
                bad += 1
                continue
            for i, w in enumerate(new):
                struct.pack_into("<I", data, off + i * 4, w)
            changed.append(off)
        if changed and not check:
            open(path, "wb").write(bytes(data))
            print("%s: patched %s"
                  % (path, ", ".join("0x%x" % o for o in changed)))
        elif changed:
            print("%s: still 7.1-order at %s"
                  % (path, ", ".join("0x%x" % o for o in changed)))
            bad += 1
        elif not check:
            print("%s: already 4.4-order" % path)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
