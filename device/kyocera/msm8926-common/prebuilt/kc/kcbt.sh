#!/system/bin/sh
#
# kcbt.sh -- put com.android.bluetooth's PackageManager state back, before
#            anybody has read it.
#
# History, because the shape of this script follows from it:
#
#   fix32's wpa hook ran `pm disable com.android.bluetooth` to stop a crash
#   loop in the 4.4 stack.  That flag does not live in any system image; it
#   lives in /data/system/users/0/package-restrictions.xml, so it survived
#   every build afterwards.  A package disabled for the user is not "an
#   adapter that fails to open": every one of its services becomes
#   unresolvable, so BluetoothManagerService.enable() dies inside
#   bindService() before any process is started and before any HAL is loaded:
#
#       D BluetoothManagerService: enable(com.android.settings): mState = OFF
#       D BluetoothManagerService: MESSAGE_ENABLE(0): mBluetooth = null
#       E BluetoothManagerService: Fail to bind to:
#              Intent { act=android.bluetooth.IBluetooth }
#
#   and the profile services fail the same way from the Settings process
#   ("Could not bind to Bluetooth HID Service with Intent {...}"), which is
#   the signature of a whole package being filtered out of resolution rather
#   than of one broken component.
#
#   fix49 tried to clear it with `pm default-state` at boot_completed.  The
#   flag was right; the timing was not.  `pm` is a shell wrapper around
#   app_process, and on this device the first one of those needs close to a
#   minute to come up while the boot is still settling.  On the fix49 boot:
#   boot_completed at 05:12:47, first pm process visible at 05:13:51, the
#   toggle tried at 05:13:58 -- four seconds after the first pm had even
#   started -- still failed.  Nothing was wrong with the idea; the repair had
#   simply not reached the flag yet.
#
#   So stop asking PackageManager to change its mind and change the file it
#   reads instead.  post-fs-data runs before zygote and long before
#   PackageManagerService parses package-restrictions.xml, so an edit there is
#   in force for the whole boot: no pm, no binder, nothing to wait for.
#
#   What is edited, and nothing else:
#
#     enabled="2" | "3" | "4"        -> enabled="0"   (back to default)
#     inst="false"                   -> removed       (pm hide / hiding; the
#                                                      attribute is spelled
#                                                      "inst" in this file)
#     stopped="true"                 -> removed       (survived force-stop)
#     hidden="true"                  -> removed
#     <disabled-components> ... </disabled-components>
#                                    -> removed, inside this package only, in
#                                       case what got disabled was a component
#                                       rather than the whole package
#
#   Everything else is copied through byte for byte, and the result goes back
#   with `cat >`, which keeps the original inode: owner, mode and SELinux
#   label are untouched.  Guards: the rewrite must still carry the
#   package-restrictions header, still end with its closing tag, and must not
#   be empty -- otherwise nothing is written.
#
#   Nothing here invents, restores or pre-fills any Bluetooth data.  It flips
#   one package's state flags and leaves a log.
#
# Usage:  kcbt.sh pre     from on post-fs-data      (this is the one that matters)
#         kcbt.sh post    from on boot_completed    (fallback, plus evidence)
#
export ANDROID_ROOT=/system
export ANDROID_DATA=/data
export ANDROID_STORAGE=/storage
export PATH=/sbin:/system/sbin:/system/bin:/system/xbin

# init exports LD_PRELOAD=/vendor/lib/libkccabi.so at post-fs-data for the sake
# of the 4.4 blobs.  This script only edits an XML file; none of that shim is
# wanted here.
unset LD_PRELOAD

LOG=/cache/kcbt.log
X=/data/system/users/0/package-restrictions.xml
PKG=com.android.bluetooth
MARK='<pkg name="com.android.bluetooth"'
MODE="${1:-post}"

say() {
    echo "KCBT $*" >> "$LOG" 2>/dev/null
}

# First line number of this package's record, empty when there is none.
lineof() {
    grep -n "$MARK" "$X" 2>/dev/null | head -1 | while IFS= read -r l; do
        echo "${l%%:*}"
    done
}

# 0 = something is not default, 1 = already default, 2 = no record to look at.
dirty() {
    n=$(lineof)
    [ -z "$n" ] && return 2
    sed -n "${n},$((n + 4))p" "$X" 2>/dev/null \
        | grep -q -e 'enabled="[234]"' -e 'inst="false"' -e 'installed="false"' \
                 -e 'stopped="true"' -e 'hidden="true"' \
                 -e '<disabled-components>'
    return $?
}

show() {
    n=$(lineof)
    [ -z "$n" ] && { say "  (no record)"; return; }
    sed -n "${n},$((n + 4))p" "$X" 2>/dev/null | while IFS= read -r l; do
        say "  $l"
    done
}

rewrite() {
    tmp=/cache/kcbt.tmp
    inside=0
    skip=0
    : > "$tmp" || return 1
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            *"$MARK"*)
                line=$(printf '%s\n' "$line" | sed \
                    -e 's/ enabled="[234]"/ enabled="0"/' \
                    -e 's/ inst="false"//' \
                    -e 's/ installed="false"//' \
                    -e 's/ stopped="true"//' \
                    -e 's/ hidden="true"//')
                printf '%s\n' "$line" >> "$tmp"
                case "$line" in
                    *'/ >'*|*'/>'*|*'</pkg>'*) inside=0 ;;
                    *) inside=1 ;;
                esac
                continue
                ;;
        esac
        if [ "$inside" = "1" ]; then
            case "$line" in
                *'<disabled-components>'*) skip=1; continue ;;
                *'</disabled-components>'*) skip=0; continue ;;
                *'</pkg>'*) inside=0 ;;
            esac
        fi
        [ "$skip" = "1" ] && continue
        printf '%s\n' "$line" >> "$tmp"
    done < "$X"

    # Guards, all of them plain greps against a file -- the first version used
    # head -c / tail -c and the header check never passed on the device, so the
    # rewrite was refused twice and the package stayed disabled until `pm` got
    # round to it a minute later.  Counting <pkg> records is the invariant that
    # actually matters anyway: this edit must never add or drop one.
    if [ ! -s "$tmp" ]; then
        say "rewrite: produced nothing, file left alone"
        rm -f "$tmp"
        return 1
    fi
    if ! grep -q "<package-restrictions" "$tmp"; then
        say "rewrite: root element missing, file left alone"
        rm -f "$tmp"
        return 1
    fi
    if ! grep -q "</package-restrictions>" "$tmp"; then
        say "rewrite: closing tag missing, file left alone"
        rm -f "$tmp"
        return 1
    fi
    b=$(grep -c "<pkg " "$X" 2>/dev/null)
    a=$(grep -c "<pkg " "$tmp" 2>/dev/null)
    if [ "$a" != "$b" ]; then
        say "rewrite: <pkg> count changed ($b -> $a), file left alone"
        rm -f "$tmp"
        return 1
    fi
    if ! cat "$tmp" > "$X"; then
        say "rewrite: write failed, file left alone"
        rm -f "$tmp"
        return 1
    fi
    rm -f "$tmp"
    return 0
}

# The Bluetooth transport is not this script's job, but it is the next thing
# after it, and the facts it needs are one command away.  qcom.bluetooth.soc is
# what makes the stack pick the two-descriptor back end (see the header note in
# kyl23-extra.rc); ro.qualcomm.bt.hci_transport is what tells the stock
# hci_qcomm_init to use /dev/smd3 instead of a UART; and /persist/.bt_nv.bin is
# where the address it programs comes from.
bttransport() {
    say "soc prop -> '$(getprop qcom.bluetooth.soc 2>&1)'"
    say "hci_transport -> '$(getprop ro.qualcomm.bt.hci_transport 2>&1)'"
    # /dev/smd* runs to two digits on this SoC -- a full `ls -l` is fifty lines
    # of log every boot and pushes the part that matters out of the dump window.
    # Only two of them are ever opened (smd3 commands+events, smd2 ACL), so the
    # count plus those two names says the same thing in one line.
    say "smd nodes: $(ls /dev/smd* 2>/dev/null | wc -l | tr -d ' ') (smd2=$([ -c /dev/smd2 ] && echo y || echo n) smd3=$([ -c /dev/smd3 ] && echo y || echo n))"
    say "bt nv: $(ls -l /persist/.bt_nv.bin 2>&1)"
    if grep -q " /persist " /proc/mounts 2>/dev/null && [ ! -s /persist/.bt_nv.bin ]; then
        # What the 4.4 ROM did at boot (init.qcom.bt.sh: program_bdaddr):
        # create NV447 if it is not there, and only then.  An address that
        # already exists is never touched, and /persist has to be a real mount
        # before anything is written into it.
        say "nv is missing -> $(/system/bin/btnvtool -O 2>&1)"
        say "nv now: $(ls -l /persist/.bt_nv.bin 2>&1)"
    fi
    say "nv content:"
    /system/bin/btnvtool -p 2>&1 | while IFS= read -r l; do say "  $l"; done
}

[ "$MODE" = "pre" ] && : > "$LOG"
# kcbtinit.sh runs as `bluetooth` and appends to this same file.
chmod 0666 "$LOG" 2>/dev/null
say "== $MODE start"
bttransport

if [ ! -f "$X" ]; then
    say "$X is not there (data not mounted yet, or never written)"
    exit 0
fi

say "file size=$(stat -c %s "$X") mode=$(stat -c %a "$X") owner=$(stat -c %u:%g "$X")"
say "before:"
show

[ "$MODE" = "pre" ] && cp -f "$X" /cache/kcbt.xml.before 2>/dev/null

dirty
d=$?
case "$d" in
    0)
        say "state is not default -> rewriting"
        if rewrite; then say "rewritten ok"; else say "rewrite failed"; fi
        say "after:"
        show
        cp -f "$X" /cache/kcbt.xml.after 2>/dev/null
        ;;
    1) say "state is already default, nothing to do" ;;
    *) say "no record for $PKG in that file" ;;
esac

# Fallback for the case where post-fs-data ran before /data was readable.  By
# then PackageManager holds the old state in memory, so the file alone cannot
# help and `pm` has to be told.  Only worth it when the file is *still* not
# default -- i.e. the rewrite did not happen, or did not stick.  `pm` costs
# close to a minute to come up on this device, and a package with no record at
# all (d=2) is already enabled, so neither of those cases pays for it.
if [ "$MODE" = "post" ]; then
    case "$d" in
        0)
            say "runtime: pm list packages -d -> $(pm list packages -d 2>/dev/null | grep -c "$PKG")"
            say "runtime: pm enable"
            say "  $(pm enable "$PKG" 2>&1)"
            say "  $(pm enable "$PKG/.btservice.AdapterService" 2>&1)"
            ;;
        1) say "post: file is default, PackageManager read it that way at boot, no pm needed" ;;
        *) say "post: no record for $PKG, package is enabled by default, no pm needed" ;;
    esac
fi

say "== $MODE done"
exit 0
