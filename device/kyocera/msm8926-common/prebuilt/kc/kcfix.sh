#!/system/bin/sh
#
# kcfix.sh -- one boot-time setting, run from post-fs-data, before the settings
#             provider is up so the database can be written safely.
#
# Android 7 permanently disables a saved network the first time its internet
# probe fails: NETWORK_SELECTION_DISABLE_THRESHOLD is 1 for
# DISABLED_NO_INTERNET and the re-enable timeout is Integer.MAX_VALUE, so one
# failed probe means "never again" -- and the probe fetches
# connectivitycheck.gstatic.com, which cannot be reached from a Chinese
# network.  That is why the phone joins at boot (the daemon reconnects on its
# own) and then refuses to join after a toggle: by then the framework has
# marked the network bad for good.
#
# CAPTIVE_PORTAL_MODE_IGNORE is 0.  It is *not* 2: 2 is
# CAPTIVE_PORTAL_MODE_AVOID, which drops the network and refuses to rejoin it --
# worse than the bug.  With IGNORE the framework never runs the probe, so a
# network without internet access is simply a network, exactly as it behaves on
# the vendor's 4.4 ROM.
#
# This touches a system setting, not Wi-Fi data: no network is created, changed
# or pre-filled here.
#
DB1=/data/user_de/0/com.android.providers.settings/databases/settings.db
DB2=/data/data/com.android.providers.settings/databases/settings.db
SQLITE=/system/xbin/sqlite3
LOG=/cache/kcfix.log
CONF=/data/misc/wifi/wpa_supplicant.conf
HIST=/data/misc/wifi/networkHistory.txt

say() {
    echo "KCFIX $*" >> "$LOG" 2>/dev/null
    echo "KCFIX $*" > /dev/kmsg 2>/dev/null
}

: > "$LOG"
say "start"

# ---------------------------------------------------------------------------
# Ownership of the supplicant files.
#
# Earlier builds ran a shell script here that rewrote these files, and a file
# rewritten by root stays root-owned.  wpa_supplicant runs as root in this
# image so it can still write them, but the framework (uid system) and the
# wifi helper binaries expect wifi:wifi 0660, and a root-owned 0600 file is
# exactly the kind of thing that makes a config silently unreadable.  Putting
# the ownership back is not "Wi-Fi data" -- the bytes do not change.
# ---------------------------------------------------------------------------
for f in "$CONF" "$CONF.bak" "$HIST"; do
    if [ -f "$f" ]; then
        chown wifi:wifi "$f" 2>/dev/null
        chmod 0660 "$f" 2>/dev/null
    fi
done
chown wifi:wifi /data/misc/wifi 2>/dev/null
chmod 0770 /data/misc/wifi 2>/dev/null
mkdir -p /data/misc/wifi/sockets 2>/dev/null
chown wifi:wifi /data/misc/wifi/sockets 2>/dev/null
chmod 0770 /data/misc/wifi/sockets 2>/dev/null
say "ownership: $(ls -ln "$CONF" "$HIST" 2>/dev/null | tr '\n' ' ')"

DB=
for c in "$DB1" "$DB2"; do
    if [ -f "$c" ]; then DB=$c; break; fi
done

if [ -z "$DB" ]; then
    say "no settings.db yet (user_de not ready), nothing written"
    exit 0
fi
if [ ! -x "$SQLITE" ]; then
    say "no sqlite3 at $SQLITE, nothing written"
    exit 0
fi

"$SQLITE" "$DB" \
    "INSERT OR REPLACE INTO global(name,value) VALUES('captive_portal_mode','0');" \
    >> "$LOG" 2>&1
"$SQLITE" "$DB" \
    "INSERT OR REPLACE INTO global(name,value) VALUES('captive_portal_detection_enabled','0');" \
    >> "$LOG" 2>&1

say "db=$DB"
say "now $("$SQLITE" "$DB" "SELECT name||'='||value FROM global WHERE name LIKE 'captive%' ORDER BY name;" 2>&1 | tr '\n' ' ')"
say "done"
exit 0
