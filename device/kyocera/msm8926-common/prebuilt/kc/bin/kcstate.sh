#!/system/bin/sh
#
# kcstate.sh -- one-shot health report for the parts of this port that still do
# not work (key backlight settings, WiFi, audio, camera, baseband).
#
# Everything is appended to /cache/kc_state.txt and the same lines are pushed
# into the kernel log as "KCST ..." so they survive on the "log" partition even
# if the cache dump gets truncated -- that is the only channel that has never
# failed us on this device.
#
# Run from init at boot_completed (and again ~2 minutes later, so the framework
# has had time to try the supplicant / audio HAL).
#
R=/cache/kc_state.txt
K=/dev/kmsg
OUT=$R

# Nothing is written to /persist: that partition carries the wifi/bt MAC,
# sensor and touch calibration, the drm keybox and rf nv data.  The report goes
# to /cache (the daemon prints the physical offset of its own log file with
# FIEMAP, so a truncated dump is no longer ambiguous) and, line by line, to
# /dev/kmsg, which lands on the "log" partition -- the only channel that has
# never lost a line on this device.
say() {
    echo "$*" >> $OUT 2>/dev/null
}

sec() { say ""; say "=== $*"; }

run() {
    # run <title> <shell snippet>
    say "--- $1"
    ( eval "$2" ) 2>&1 | head -n 60 | while IFS= read -r l; do say "    $l"; done
}

/vendor/bin/kcboot mknod 2>/dev/null

# Keep the previous pass in the file (two passes per boot), but start over if
# it has grown over a few boots.
SZ=$(stat -c %s $R 2>/dev/null)
[ -n "$SZ" ] && [ "$SZ" -gt 400000 ] && : > $R

# A copy of the provider database is worth more than any reading of it: it can
# be parsed offline with a real sqlite3, and it shows what the page actually
# stored (or that it stored nothing at all).
snap_db() {
    for d in /data/user_de/0/org.cyanogenmod.cmsettings/databases \
             /data/user/0/org.cyanogenmod.cmsettings/databases \
             /data/data/org.cyanogenmod.cmsettings/databases; do
        [ -f "$d/cmsettings.db" ] || continue
        say "DB $d/cmsettings.db $(stat -c %s "$d/cmsettings.db" 2>/dev/null) bytes"
        ls -l "$d" 2>&1 | head -8 | while IFS= read -r l; do say "    $l"; done
        # a copy is far more useful than any reading of it: it can be opened
        # offline with a real sqlite3
        cp -f "$d/cmsettings.db" /cache/kc_cmsettings.db 2>/dev/null && \
            say "DB copied to /cache/kc_cmsettings.db"
        for x in -wal -journal; do
            [ -f "$d/cmsettings.db$x" ] && \
                cp -f "$d/cmsettings.db$x" "/cache/kc_cmsettings.db$x" 2>/dev/null && \
                say "DB sidecar $x copied ($(stat -c %s "$d/cmsettings.db$x") bytes)"
        done
        say "DB times: $(stat -c '%n size=%s mtime=%Y %y' "$d/cmsettings.db" 2>&1)"
        return 0
    done
    say "DB not found in any of the three provider directories"
    return 1
}
SKIP=$(wc -l < $R 2>/dev/null)
[ -z "$SKIP" ] && SKIP=0
say "KCSTATE begin $(date) (fix34)"

# ---------------------------------------------------------------------------
# fix29: the two questions this round left open.
#
# 1. "Reboot sat on the spinner for eight minutes."
#    Everything userspace knows is already in /cache/kc_shut.log, and it ends
#    with the process being killed by the shutdown itself -- i.e. the wait is
#    below us, in the kernel.  The previous kernel's ring buffer survives this
#    port as /proc/last_kmsg (msm ram console) or in pstore, so dump it: it is
#    the only place that can still say what the reboot path was waiting on.
#
# 2. "Camera takes 40 s to show a picture, but switching lenses is instant."
#    That is not the camera being slow to open.  logcat shows
#      CameraManagerGlobal: Connecting to camera service
#      CameraManagerGlobal: Camera service is unavailable
#    once a second for the first ~40 s of a session: mediaserver has not
#    published media.camera yet, because its CameraService constructor walks
#    the HAL, and the HAL pays a fixed delay per sensor start (DSPS/sensor1 is
#    dead, "Failed to open sensor1 port").  Capture that timeline explicitly.
# ---------------------------------------------------------------------------
sec "fix29 shutdown"
run "last_kmsg" 'ls -l /proc/last_kmsg 2>&1; echo "--- tail:"; tail -n 70 /proc/last_kmsg 2>/dev/null'
run "pstore" 'ls -l /sys/fs/pstore 2>&1 | head -6; for f in /sys/fs/pstore/dmesg*; do [ -f "$f" ] && tail -n 40 "$f"; done 2>/dev/null'
run "halt state" 'echo "sysrq=$(ls -l /proc/sysrq-trigger 2>&1)"; echo "powerctl=[$(getprop sys.powerctl)] requested=[$(getprop sys.shutdown.requested)]"; echo "--- kc_shut.log:"; cat /cache/kc_shut.log 2>/dev/null'

sec "fix29 camera"
run "service timeline" '/system/bin/logcat -d -v time -b all 2>/dev/null | grep -E "CameraManagerGlobal|CameraService|QCamera2HWI|mm_camera_open|start_preview|Camera 0|Camera 1" | tail -n 40'
run "sensor1" '/system/bin/logcat -d -v time -b all 2>/dev/null | grep -i -E "sensor1|dsps|gyro_module|module_sensor_start" | tail -n 20'
run "kccam" 'dmesg 2>/dev/null | grep KCCAM | tail -n 30'
run "kccam tail file" 'for f in /cache/kc_tail.log*; do [ -f "$f" ] || continue; echo "== $f $(stat -c %s "$f" 2>/dev/null)"; grep -a -E "CameraManagerGlobal|QCamera2HWI|mm_camera_open" "$f" 2>/dev/null | tail -n 12; done'

sec "fix29 wifi conf"
run "config" 'C=/data/misc/wifi/wpa_supplicant.conf; ls -l $C 2>&1; grep -n -E "update_config|ctrl_interface|network=|ssid=|key_mgmt=|disabled=|priority=" $C 2>/dev/null | head -20'
run "counts" 'C=/data/misc/wifi/wpa_supplicant.conf; echo "upd=$(grep -c "^update_config=1" $C 2>/dev/null) psk=$(grep -c "psk=" $C 2>/dev/null) dis=$(grep -c "disabled=1" $C 2>/dev/null) bootcount=$(cat /cache/kc_boot.count 2>/dev/null)"'
run "wifi kmesg" 'dmesg 2>/dev/null | grep -E "KCWIFI|KCWIFD|KCFS|KCCAM" | tail -n 12'
run "wifi driver" 'echo "prop=[$(getprop wlan.driver.status)] supp=[$(getprop init.svc.wpa_supplicant)] p2p=[$(getprop init.svc.p2p_supplicant)]"; grep -E "^wlan " /proc/modules; ls -l /sys/class/net/wlan0 2>&1 | head -2; cat /sys/class/net/wlan0/address 2>/dev/null; echo "state=$(getprop dhcp.wlan0.ipaddress)"'
run "wifi conn" '/system/bin/logcat -d -v time -b all 2>/dev/null | grep -i -E "WifiMonitor|Failed to load driver|startSupplicant|CTRL-EVENT|WifiConfigManager|saveConfig|NETWORK" | tail -n 25'

# ---------------------------------------------------------------------------
# fix31: the two things that were still unexplained, asked directly.
#
# 1. The shutter.  Pressing it brings up "cannot connect to the camera" at
#    once and then ANRs the app.  logcat has the sequence up to
#    take_picture -> YUV callback -> EXIF built -> silence -> stop_preview
#    four seconds later, and no JPEG line at all -- but every log that could
#    have carried the JPEG side was full of per-frame preview spam, so that
#    silence proves nothing yet.  Ask the encoder directly instead: the node
#    it needs, whether the kernel ever saw a JPEG job, and what the app's own
#    error callback said.
#
# 2. WiFi after an off/on cycle.  fix30 proved the password is on disk; this
#    round made the file hold exactly one enabled network.  What is left to
#    see is whether the framework managed to reload it after the supplicant
#    was restarted, which WifiConfigManager logs as a line count.
# ---------------------------------------------------------------------------
sec "fix31 camera shutter"
run "jpeg nodes" 'ls -l /dev/msm_jpeg* /dev/jpeg* 2>&1 | head -n 6; echo "--- jpeg sysfs:"; ls /sys/kernel/*jpeg* /sys/class/*jpeg* 2>&1 | head -n 6'
run "jpeg kernel" 'dmesg 2>/dev/null | grep -i "jpeg" | tail -n 15'
run "camera errors" '/system/bin/logcat -d -v time -b all 2>/dev/null | grep -E "Camera2Client|Camera3Device|CameraActivity|Camera error|onError|takePicture|take_picture|ANR in|not responding" | tail -n 30'
run "camera procs" 'ps 2>/dev/null | grep -E "camera|media" | head -n 8'
run "KCCAM" 'dmesg 2>/dev/null | grep KCCAM | tail -n 30'
run "cam tail" 'for f in /cache/kc_tail.log*; do [ -f "$f" ] || continue; echo "== $f $(stat -c %s "$f" 2>/dev/null)"; grep -a -E "Camera error|Camera2Client|takePicture|ANR in|WifiStateMachine|WifiConfigManager|WifiMonitor" "$f" 2>/dev/null | tail -n 10; done'

sec "fix31 wifi"
run "conf" 'C=/data/misc/wifi/wpa_supplicant.conf; echo "size=$(stat -c %s $C 2>/dev/null) blocks=$(grep -c "^network=" $C 2>/dev/null)"; grep -n -E "^network=|ssid=|psk=|disabled=|update_config=" $C 2>/dev/null | head -n 12'
run "history" 'ls -l /data/misc/wifi/networkHistory.txt /cache/kc_networkHistory.old 2>&1'
run "state" 'echo "p2p=[$(getprop init.svc.p2p_supplicant)] wpa=[$(getprop init.svc.wpa_supplicant)] drv=[$(getprop wlan.driver.status)] ip=[$(getprop dhcp.wlan0.ipaddress)]"; cat /sys/class/net/wlan0/operstate 2>/dev/null'
run "wifi log" '/system/bin/logcat -d -v time -b all 2>/dev/null | grep -E "WifiStateMachine|WifiMonitor|WifiConfigManager|Failed to load driver|supplicant" | tail -n 30'
run "KCWIFI" 'dmesg 2>/dev/null | grep KCWIFI | tail -n 10'

# ---------------------------------------------------------------------------
# fix32: the WiFi off/on cycle and the bluetooth crash loop.
#
# The conf on disk is now the whole story: the framework never adopts the saved
# network (it rebuilds it with a made-up netId, logs "configuration found for
# missing network ... ignored" and holds zero networks), the supplicant joins
# it by itself at boot, and WifiConfigStore.saveConfig() then deletes it from
# disk on the first WiFi off because its list is empty.  kcwifi3.sh puts the
# file back and SIGHUPs the supplicant; these lines say whether it had to.
# ---------------------------------------------------------------------------
sec "fix32 wifi guard"
run "conf full" 'C=/data/misc/wifi/wpa_supplicant.conf; echo "size=$(stat -c %s $C 2>/dev/null) blocks=$(grep -c "^network=" $C 2>/dev/null) psk=$(grep -c "psk=" $C 2>/dev/null) dis=$(grep -c "disabled=" $C 2>/dev/null)"; sed -n "1,45p" $C 2>/dev/null'
run "gold" 'ls -l /data/misc/wifi/kc_wpa.gold /cache/kc_wpa.gold /cache/kc_wpa.old 2>&1'
run "guard svc" 'echo "svc=[$(getprop init.svc.kcwifi3)] pid=[$(pidof kcwifi3.sh 2>/dev/null)]"; dmesg 2>/dev/null | grep KCWIFI3 | tail -n 12'
run "guard log" 'tail -n 25 /cache/kcwifi3.log 2>&1'
run "toggles" '/system/bin/logcat -d -v time -b all 2>/dev/null | grep -E "setWifiEnabled|SAVE_NETWORK|CONNECT_NETWORK|Loading config and enabling|configuration found for missing" | tail -n 25'

sec "fix32 bluetooth"
run "restarts" 'echo "deaths=$(/system/bin/logcat -d -b all 2>/dev/null | grep -c "com.android.bluetooth (pid .* has died")"; echo "faults=$(dmesg 2>/dev/null | grep -c "USRFLT droid.bluetooth")"; echo "svc=[$(getprop init.svc.bluetooth)]"'
run "fault detail" 'dmesg 2>/dev/null | grep -E "USRFLT droid.bluetooth|USRFLT pc .*libbluetooth_jni" | tail -n 8'
run "us" 'dmesg 2>/dev/null | grep -E "USRFLT BluetoothAdapte|USRFLT bluetooth" | tail -n 6'

# ---------------------------------------------------------------------------
# fix33: the daemon that talks to the supplicant.
#
# The conf file was never the problem in the last session: it was intact, one
# block, psk, no disabled -- and the phone still would not reconnect after an
# off/on cycle.  What the framework does with it is the problem: it rebuilds
# the network, gets nid=-1616136200 (the hashCode of "K2"WPA_PSK) instead of
# the supplicant's id, fails to match it against its own (empty) list and drops
# it, so WifiConnectivityManager has no candidate and never asks the supplicant
# to connect.  At boot the supplicant joins on its own before that can matter;
# after a switch cycle it just scans.
#
# kcwpad closes that gap by speaking wpa_ctrl to the supplicant directly.  The
# lines below are its own log plus the state it saw, so the next dump says
# whether the kick worked, was refused, or the socket was not reachable.
# ---------------------------------------------------------------------------
sec "fix34 wifi daemon"
run "svc" 'echo "svc=[$(getprop init.svc.kcwpad)]"; ls -l /vendor/bin/kcwpad /dev/kmsg 2>&1'
run "log" 'tail -n 70 /cache/kcwpad.log 2>&1'
run "log old" 'ls -l /cache/kcwpad.log* 2>&1; tail -n 15 /cache/kcwpad.log.1 2>&1'
run "kmsg" 'dmesg 2>/dev/null | grep KCWPAD | tail -n 25'
run "sockets" 'ls -l /data/misc/wifi/sockets/ 2>&1 | head -12'
run "wpa state" 'echo "iface=$(cat /sys/class/net/wlan0/operstate 2>/dev/null) ip=$(ip addr show wlan0 2>/dev/null | grep "inet " | head -1)"'
run "wpa proc" 'for d in /proc/[0-9]*; do c=$(tr "\0" " " < $d/cmdline 2>/dev/null); case "$c" in *wpa_supplicant*) echo "${d#/proc/} $c";; esac; done'
run "scan results" '/system/bin/dumpsys wifi 2>/dev/null | grep -E "mScanDetail|WifiScanner|Scan results|latest scan" | head -8'
run "saved nets" '/system/bin/dumpsys wifi 2>/dev/null | grep -A3 "Configured networks" | head -12'

sec "fix34 camera hal"
run "viewing patch" 'for f in /vendor/lib/camera.qc.so; do echo "$f $(stat -c %s $f 2>/dev/null) $(od -A n -t x1 -j $((0x71f94)) -N 4 $f 2>/dev/null)"; done'
run "screenshot svc" '/system/bin/service list 2>/dev/null | grep -i screenshot; echo "(none above = the 4s stall source)"'
run "timeline" '/system/bin/logcat -d -v time -b all 2>/dev/null | grep -E "openCamera|stop_preview|GlobalScreenshot|No memory pool|module_sensor_start_session|CameraFlashlight|takePicture|take_picture" | tail -n 30'
run "errors" '/system/bin/logcat -d -v time -b all 2>/dev/null | grep -E "CameraService|CameraManagerGlobal|AndroidRuntime|CAM_" | tail -n 20'

sec "fix33 bluetooth off"
run "pkg" 'grep -o "package=\"com.android.bluetooth\"[^>]*" /data/system/users/0/package-restrictions.xml 2>/dev/null | head -3; echo "enabled=$(/system/bin/pm list packages -e 2>/dev/null | grep -c com.android.bluetooth) disabled=$(/system/bin/pm list packages -d 2>/dev/null | grep -c com.android.bluetooth)"'
run "state" 'echo "prop=[$(getprop bluetooth.enable_timeout_ms)]"; /system/bin/dumpsys bluetooth_manager 2>/dev/null | head -8; echo "procs=$(ls /proc | grep -c "^[0-9]*$")"'

# ---------------------------------------------------------------------------
# fix28: what killed the framework.
#
# fix27 made the boot fast and the system then fell over the moment the first
# sound was played: audioserver died with SIGSEGV in its AudioOut thread the
# instant the audio HAL started the output stream, media.audio_policy never
# came back, system_server's *main* thread sat in
#     ServiceManager: Waiting for service media.audio_policy...
# and the 60 s watchdog killed system_server -- that is the "soft reboot" that
# never seemed to finish.
#
# None of that was visible in the dump: a soft reboot leaves a DeadSystem
# exception in the app and nothing else, the crash buffer is small, and a
# tombstone lives in /data, which the dump does not carry.  So copy them out.
# ---------------------------------------------------------------------------
sec "crashes (fix28)"
run "tombstones" 'ls -l /data/tombstones 2>&1 | tail -n 12; echo "--- dropbox:"; ls -l /data/system/dropbox 2>&1 | tail -n 8'
for t in $(ls -t /data/tombstones/tombstone_* 2>/dev/null | head -n 3); do
    cp -f "$t" "/cache/kc_$(basename $t)" 2>/dev/null && \
        say "copied $t -> /cache/kc_$(basename $t) ($(stat -c %s "$t" 2>/dev/null) bytes)"
done
run "crash buffer" '/system/bin/logcat -d -v time -b crash 2>/dev/null | tail -n 40'
run "anr watchdog" '/system/bin/logcat -d -v time -b all 2>/dev/null | grep -E "Watchdog|WATCHDOG|ANR in|am_anr|DeadSystem|has died|Blocked in" | tail -n 30'
run "faults" '/system/bin/logcat -d -v time -b all 2>/dev/null | grep -E "FATAL|fault addr|signal 11|signal 6" | tail -n 20'
run "audio death" '/system/bin/logcat -d -v time -b all 2>/dev/null | grep -E "audioserver|AudioService|AudioPolicyService|audio_policy|audio_hw_primary|AudioFlinger" | tail -n 30'
run "audio live" 'echo "policy=$(service check media.audio_policy 2>/dev/null) flinger=$(service check media.audio_flinger 2>/dev/null) audio=$(service check audio 2>/dev/null)"; echo "hal=$(ls -l /vendor/lib/hw/audio.primary.msm8226.so 2>&1)"; echo "cards=$(cat /proc/asound/cards 2>/dev/null | tr "\n" "|")"; echo "audioserver=$(getprop init.svc.audioserver)"'
run "bt now" 'echo "bt=$(getprop init.svc.bluetoothd) crash=$(getprop init.svc.vendor.bluetooth)"; echo "iface=$(hciconfig 2>&1 | head -3)"; echo "prop=$(getprop bluetooth.enable_timeout_ms)"; ls -l /vendor/lib/hw/bluetooth.default.so /vendor/lib/libbtfix.so 2>&1'

# ---------------------------------------------------------------------------
# fix25: everything that decides whether the modem and the ADSP can work.
# This block is deliberately first in the file: the cache dump only carries the
# first 20 MB of the partition, and these are the lines that matter most.
# ---------------------------------------------------------------------------
sec "fix25 boot"
run "sys/kernel" 'ls -l /sys/kernel 2>&1 | head -30'
run "subsys detail" 'for d in /sys/bus/msm_subsys/devices/*; do echo "[$(basename $d)] $(cat $d/name 2>/dev/null)"; echo "  state=$(cat $d/state 2>/dev/null) level=$(cat $d/restart_level 2>/dev/null) crashes=$(cat $d/crash_count 2>/dev/null) fw=$(cat $d/firmware_name 2>/dev/null)"; echo "  attrs: $(ls $d 2>/dev/null | tr "\n" " ")"; done'
run "cmdline" 'cat /proc/cmdline'
run "firmware" 'ls -l /firmware 2>&1 | head -20; echo "--- image:"; ls /firmware/image 2>&1 | head -40'
run "radio props" 'getprop 2>/dev/null | grep -i -E "baseband|radio|ril\.|gsm\.|persist.radio" | head -40'
run "procs" 'for p in /proc/[0-9]*; do c=$(tr "\0" " " < $p/cmdline 2>/dev/null); [ -n "$c" ] && echo "${p#/proc/} $c"; done | head -60'

sec "modem fixes"
run "kcadsp" 'tail -n 60 /cache/kcadsp.log 2>&1'
run "kcssr" 'tail -n 40 /cache/kcssr.log 2>&1'
run "bt crash" 'ls -l /cache/bt_crash.txt 2>&1; echo "---"; head -c 6000 /cache/bt_crash.txt 2>&1'

# The full kernel log and the radio buffer are written as files: both are far
# too long to mirror into the state report, and both are what the modem
# questions need.
dmesg > /cache/kc_dmesg.txt 2>/dev/null
say "dmesg -> /cache/kc_dmesg.txt $(wc -l < /cache/kc_dmesg.txt 2>/dev/null) lines"
/system/bin/logcat -d -b radio -v time > /cache/kc_radio.txt 2>/dev/null
say "radio log -> /cache/kc_radio.txt $(wc -l < /cache/kc_radio.txt 2>/dev/null) lines"
run "radio tail" 'tail -n 40 /cache/kc_radio.txt 2>&1'

sec "kcbtnled"
run "svc" 'echo "pid=$(pidof kcbtnled)"; echo "svc=$(getprop init.svc.kcbtnled)"; echo "ppid=$(cut -d" " -f4 /proc/$(pidof kcbtnled)/stat 2>/dev/null)"; ps -o pid,ppid,rss,stat,args -p $(pidof kcbtnled) 2>&1'
run "sinks" 'ls -l /cache/kclog.txt /cache/kc_btn.log /data/misc/kcbtnled.log /data/local/tmp/kclog.txt 2>&1'
run "log" 'tail -n 80 /cache/kclog.txt 2>&1'
run "phys" 'grep -E "phys |sinks:" /cache/kclog.txt 2>&1 | tail -12'
run "settings section" 'snap_db'

sec "props"
run "init.svc" 'for p in kcbtnled kcbtnled_sync kcwifi wpa_supplicant p2p_supplicant adsprpcd kcdiag kcdiag2; do echo "$p=$(getprop init.svc.$p)"; done; echo "boot_completed=$(getprop sys.boot_completed)"; echo "wifi.interface=$(getprop wifi.interface)"; echo "build=$(getprop ro.build.version.release)/$(getprop ro.build.type)"'

sec "kernel modules"
run "wlan" 'grep -E "^(wlan|cfg80211|prima)" /proc/modules 2>&1; echo "sys/module:"; ls /sys/module | grep -i -E "wlan|prima|cfg80211" 2>&1; echo "unloading:"; cat /sys/module/wlan/refcnt 2>&1'

sec "network"
run "interfaces" 'ls /sys/class/net; echo "wlan0 mac=$(cat /sys/class/net/wlan0/address 2>/dev/null)"; echo "wlan0 oper=$(cat /sys/class/net/wlan0/operstate 2>/dev/null)"; cat /proc/net/dev | tail -n +3'

sec "wcnss ssr"
run "levels" 'for d in /sys/bus/msm_subsys/devices/subsys*; do echo "$(basename $d) fw=$(cat $d/firmware_name 2>/dev/null) level=$(cat $d/restart_level 2>/dev/null) cnt=$(cat $d/restart_count 2>/dev/null)"; done; echo "bootcount=$(cat /cache/kc_boot.count /data/misc/kc_boot.count 2>/dev/null | tr "\n" " " ) paniconoops=$(cat /proc/sys/kernel/panic_on_oops 2>/dev/null)"'
run "crashes" 'dmesg 2>/dev/null | grep -E "wcnss|subsys-restart|VOS |kernel BUG|KCSSR|KCFS" | tail -n 25'

sec "wifi state"
run "files" 'ls -l /data/misc/wifi 2>&1; echo "sockets:"; ls -l /data/misc/wifi/sockets 2>&1'
# Where does the illumination tick box end up?  fix22 reads every store that can
# hold the two keys, so the report lists them all with their mtime and prints
# the app's own transcript of the tick box.
sec stores
run "stores" 'for f in /data/user_de/0/org.cyanogenmod.cmsettings/databases/cmsettings.db /data/user/0/org.cyanogenmod.cmsettings/databases/cmsettings.db /data/data/org.cyanogenmod.cmsettings/databases/cmsettings.db /data/system/users/0/settings_secure.xml /data/system/users/0/cmsettings_secure.xml /data/user_de/0/org.cyanogenmod.cmparts/shared_prefs/org.cyanogenmod.cmparts_preferences.xml /data/user/0/org.cyanogenmod.cmparts/shared_prefs/org.cyanogenmod.cmparts_preferences.xml; do echo "$(stat -c "%s@%y" "$f" 2>/dev/null || echo -) $f"; done'
run "pref" 'cat /data/user_de/0/org.cyanogenmod.cmparts/shared_prefs/*.xml /data/user/0/org.cyanogenmod.cmparts/shared_prefs/*.xml 2>/dev/null | head -n 25'
run "state" 'cat /data/misc/kcbtnled.state 2>/dev/null'
run "lc" 'tail -n 30 /cache/lc.txt 2>/dev/null'
cp -f /data/user/0/org.cyanogenmod.cmsettings/databases/cmsettings.db /cache/kc_ce.db 2>/dev/null
cp -f /data/user/0/org.cyanogenmod.cmparts/shared_prefs/org.cyanogenmod.cmparts_preferences.xml /cache/kc_pref.xml 2>/dev/null
cp -f /data/user_de/0/org.cyanogenmod.cmparts/shared_prefs/org.cyanogenmod.cmparts_preferences.xml /cache/kc_pref_de.xml 2>/dev/null

run "wpa conf" 'C=/data/misc/wifi/wpa_supplicant.conf; echo "nets=$(grep -c \"^[[:space:]]*network={\" $C 2>/dev/null) psk=$(grep -c \"^[[:space:]]*psk=\" $C 2>/dev/null) disabled=$(grep -c \"^[[:space:]]*disabled=1\" $C 2>/dev/null) upd=$(grep -c \"update_config=1\" $C 2>/dev/null)"; grep -E "^[[:space:]]*(ssid|key_mgmt|disabled|priority)=" $C 2>/dev/null | head -20'
run "net hist" 'grep -E "CONFIG|SSID|NETWORK_SELECTION|HAS_EVER_CONNECTED" /data/misc/wifi/networkHistory.txt 2>/dev/null | head -20'
run "wpa log" 'tail -30 /cache/wpa.log 2>&1; echo "----"; tail -15 /cache/kc_wifi.txt 2>&1'

sec "key backlight"
run "conf" 'cat /data/misc/kcbtnled.conf 2>&1'
run "daemon log" 'tail -40 /cache/kc_btn.log 2>&1'
run "sync log" 'tail -40 /cache/kc_sync.log 2>&1'
run "led nodes" 'ls /sys/class/leds; echo "btn=$(cat /sys/class/leds/button-backlight/brightness 2>&1) max=$(cat /sys/class/leds/button-backlight/max_brightness 2>&1)"'

sec "cmsettings database"
run "dirs" 'for d in /data/data/org.cyanogenmod.cmsettings/databases /data/user/0/org.cyanogenmod.cmsettings/databases /data/user_de/0/org.cyanogenmod.cmsettings/databases; do echo "$d:"; ls -l $d 2>&1 | head -6; done'
run "times" 'for f in /cache/kc_cmsettings.db /cache/kc_cmsettings.db-wal /cache/kc_cmsettings.db-journal; do [ -f $f ] && stat -c "%n %s %y" $f; done; echo "---"; ls -l /cache | head -12'
run "dump" 'SQL=; for c in /system/xbin/sqlite3 /system/bin/sqlite3 /xbin/sqlite3; do [ -x $c ] && { SQL=$c; break; }; done; DB=/cache/kc_cmsettings.db; [ -f $DB ] || DB=$(ls /data/*/0/org.cyanogenmod.cmsettings/databases/cmsettings.db /data/data/org.cyanogenmod.cmsettings/databases/cmsettings.db 2>/dev/null | head -1); echo "sql=$SQL db=$DB"; $SQL "$DB" ".dump secure" 2>&1 | grep -i -E "button|INSERT INTO secure" | head -40; echo "--- counts:"; for t in secure system global; do echo "$t=$($SQL "$DB" "select count(*) from $t" 2>&1)"; done'
run "rows" 'SQL=; for c in /system/xbin/sqlite3 /xbin/sqlite3 /system/bin/sqlite3; do [ -x $c ] && { SQL=$c; break; }; done; echo "sql=$SQL"; $SQL -version 2>&1; DB=; for d in /data/data/org.cyanogenmod.cmsettings /data/user/0/org.cyanogenmod.cmsettings /data/user_de/0/org.cyanogenmod.cmsettings; do [ -f $d/databases/cmsettings.db ] && DB=$d/databases/cmsettings.db && break; done; echo "db=$DB"; for t in secure system global; do echo "[$t]"; $SQL -cmd ".timeout 3000" "$DB" "select name,value from $t where name like \"%bright%\" or name like \"%backlight%\" or name like \"%button%\"" 2>&1 | head -20; done'

run "ls" 'ls -l /system/xbin/sqlite3 /system/xbin 2>&1 | head -20; echo "--- /xbin:"; ls -l /xbin 2>&1 | head -3'

sec "processes"
run "ps" 'ps -A 2>/dev/null | grep -E "wpa|supplicant|adsprpc|kcbtnled|qmuxd|netmgrd" | head -20'
run "unix" 'cat /proc/net/unix 2>/dev/null | grep -i -E "wpa|supplicant" | head -10'
run "svc" 'for p in wpa_supplicant p2p_supplicant kcwifi kcbtnled kcbtnled_sync; do echo "$p=$(getprop init.svc.$p)"; done'

sec "adsp"
run "state" 'for d in /sys/bus/msm_subsys/devices/subsys*; do echo "$(basename $d) $(cat $d/firmware_name 2>/dev/null) state=$(cat $d/state 2>/dev/null) level=$(cat $d/restart_level 2>/dev/null)"; done'
run "dt" 'for f in /proc/device-tree/soc/qcom,msm-adsp-loader/*; do echo "$(basename $f) size=$(wc -c < $f 2>/dev/null)"; done 2>&1'
run "sysfs" 'ls /sys/kernel/boot_adsp 2>&1; ls -d /sys/devices/platform/*adsp* 2>&1'
run "fw" 'ls -l /firmware/image 2>/dev/null | head -20; ls /firmware 2>&1'
run "log" 'dmesg | grep -i -E "KCADSP|adsp|adsprpc|apr|subsys-restart" | tail -30'

sec "audio"
run "cards" 'cat /proc/asound/cards 2>&1; echo "dev:"; ls /dev/snd 2>&1; echo "pcm:"; ls /proc/asound 2>&1'
run "slimbus" 'ls /sys/bus/slimbus/devices 2>&1; for d in /sys/bus/slimbus/devices/*; do echo "$d name=$(cat $d/name 2>/dev/null)"; done'
run "dmesg" 'dmesg | grep -i -E "tapan|wcd9|slimbus|asoc|msm_pcm|msm-pcm|apr|adsp|lpass" | tail -40'
run "hal" 'logcat -d -v time -b all -t 2000 2>/dev/null | grep -i -E "audio_hw|AudioPolicy|AudioFlinger|audioserver" | tail -20'

sec "camera"
run "sys" 'ls /sys/class/camera 2>&1; ls -l /dev/video* 2>&1 | head; ls -l /vendor/lib/hw/camera* 2>&1'
run "dmesg" 'dmesg | grep -i -E "cci|csid|csiphy|imx|ov[0-9]|s5k|msm_cci|camera" | tail -30'
run "hal" 'logcat -d -v time -b all -t 2000 2>/dev/null | grep -i -E "CameraService|CameraModule|QCamera|mm-camera|qcamerasvr" | tail -25'


sec "camera (fix26)"
run "hal files" 'ls -l /vendor/lib/libmmcamera_faceproc.so /vendor/lib/hw/camera.msm8226.so /vendor/lib/camera.qc.so /vendor/bin/mm-qcamera-daemon 2>&1'
# The daemon and the HAL only ever log to logcat, and those messages are the
# only way to see which sensor lib was picked and why a session refused to
# start.  Keep them in their own file: they are too long for the report.
/system/bin/logcat -d -v time -b all -s mm-camera:V mm-camera-sensor:V mm-camera-img:V mm-camera-intf:V QCamera2HWI:V QCameraParameters:V QCameraHWI_Mem:V 2>/dev/null | tail -n 1200 > /cache/kc_camera.txt
say "camera log -> /cache/kc_camera.txt $(wc -l < /cache/kc_camera.txt 2>/dev/null) lines"
run "camera tail" 'tail -n 30 /cache/kc_camera.txt 2>&1'
run "camera errors" 'grep -i -E "failed|error|not supported|not found" /cache/kc_camera.txt 2>/dev/null | tail -n 25'
run "procs" 'ls -l /proc/*/exe 2>/dev/null | grep -i -E "camera|daemon" | head'

sec "modem (fix26)"
run "restart_level" 'for d in /sys/bus/msm_subsys/devices/*; do echo "$(basename $d) $(cat $d/name 2>/dev/null) state=$(cat $d/state 2>/dev/null) level=$(cat $d/restart_level 2>/dev/null) mode=$(ls -ld $d/restart_level 2>/dev/null | cut -c1-10)"; done'
run "failure reason" 'dmesg | grep -i -E "subsystem failure reason|SMSM|Notify|halt timeout|ramdump" | tail -n 25'
run "qmi" 'ls -l /dev/qmi* /dev/smdcntl0 /dev/smdcntl1 2>&1'
run "qmuxd" 'ps 2>/dev/null | grep -E "qmuxd|netmgrd|rmt_storage|rild" | head'
run "baseband prop" 'getprop 2>/dev/null | grep -i -E "gsm.version.baseband|gsm.sim.state|ril.iccid|ro.baseband"'


sec "adsp (fix27)"
run "subsys0" 'echo "state=$(cat /sys/bus/msm_subsys/devices/subsys0/state 2>/dev/null) level=$(cat /sys/bus/msm_subsys/devices/subsys0/restart_level 2>/dev/null)"; ls -l /sys/bus/msm_subsys/devices/subsys0 2>&1'
run "boot_adsp" 'ls -l /sys/kernel/boot_adsp 2>&1; for f in /sys/kernel/boot_adsp/*; do echo "$(basename $f) = $(cat $f 2>&1)"; done'
run "dt" 'for f in /proc/device-tree/soc/qcom,msm-adsp-loader/*; do echo "$(basename $f) size=$(wc -c < "$f" 2>/dev/null)"; done 2>&1'
run "log" 'tail -n 40 /cache/kcadsp.log 2>&1'
run "ssr" 'tail -n 20 /cache/kcssr.log 2>&1'
run "sound" 'cat /proc/asound/cards 2>&1; echo "--- slimbus:"; ls /sys/bus/slimbus/devices 2>&1; echo "--- snd:"; ls /dev/snd 2>&1'
run "audio props" 'getprop 2>/dev/null | grep -i -E "audio|media\." | head -20; echo "--- service:"; /system/bin/service list 2>/dev/null | grep -i audio'

sec "boot timing (fix27)"
run "uptime" 'cat /proc/uptime; echo "boot_complete=$(getprop sys.boot_completed) bootanim=$(getprop service.bootanim.exit)"'
run "boot events" '/system/bin/logcat -d -v time -b events 2>/dev/null | grep -E "boot_progress|sf_stop_bootanim|am_proc_start" | head -25'


sec "firmware (fix27)"
run "verinfo" 'ls -l /firmware/verinfo 2>&1; for f in /firmware/verinfo/*; do echo "== $(basename $f)"; head -c 2000 "$f" 2>/dev/null; echo; done'
run "images" 'ls -l /firmware/image 2>&1 | head -n 60'
run "adsp image" 'ls -l /firmware/image/adsp* 2>&1; echo "--- mdt:"; ls -l /firmware/image/*.mdt 2>&1 | head -n 10'
run "modem state" 'for i in 1 2 3; do echo "t$i $(cat /sys/bus/msm_subsys/devices/subsys1/state 2>/dev/null) power=$(cat /sys/bus/msm_subsys/devices/subsys1/power 2>/dev/null)"; sleep 1; done'

sec "bluetooth (fix27)"
run "crash count" '/system/bin/logcat -d -b all 2>/dev/null | grep -c "com.android.bluetooth (pid .* has died"'
run "recent" '/system/bin/logcat -d -v time -b all -t 2000 2>/dev/null | grep -i -E "bluetooth|btif|bluedroid|bte_conf" | tail -30'

sec "bluetooth"
run "hal" 'ls -l /vendor/lib/libbtfix.so /vendor/lib/hw/bluetooth.default.so 2>&1'
run "log" 'logcat -d -v time -b all -t 2000 2>/dev/null | grep -i -E "bluetooth|Bluetooth|hci" | tail -25'

sec "modem / baseband"
run "subsys" 'ls /sys/bus/msm_subsys/devices 2>&1; for d in /sys/bus/msm_subsys/devices/*; do echo "$d $(cat $d/name 2>/dev/null) state=$(cat $d/state 2>/dev/null)"; done'
run "dmesg" 'dmesg | grep -i -E "modem|mss|q6v5|smem|pil_|subsys" | tail -40'
run "rmt" 'tail -6 /cache/kc_diag.txt 2>&1'

sec "logcat"
run "settings errors" '/system/bin/logcat -d -v time -b all -t 4000 2>/dev/null | grep -i -E "cmparts|cmsettings|SQLite|sqlite|SecurityException|Backlight" | tail -40'
run "tail" '/system/bin/logcat -d -v time -b all -t 3000 2>/dev/null | grep -i -E "wpa|supplicant|WifiHW|WifiStateMachine|WifiNative|qmuxd|RIL |audio_hw|AudioPolicy|adsprpc|mm-camera|kcbtnled|cmsettings" | tail -90'

sec "cache files"
run "list" 'ls -l /cache 2>&1 | head -30'

say ""
say "KCSTATE end $(date)"

# Mirror a short digest into the kernel log.  A 600 line burst is dropped by
# printk's rate limiter -- only 6 lines of the last round survived -- so keep it
# to one line in eight and pause between them.
tail -n +$((SKIP + 1)) $R 2>/dev/null | grep -E "^(===|---|    (settings: b=|led off|hits |dbwatch|phys |DB |nets=|wpa conf|stores|pref|state|lc|src: |from=|pid=|subsys[0-9]|bootcount=|KCSSR|KCFS|KCADSP|adsp|slimbus|bluetooth|Camera|sysfs))" | head -n 12 | while IFS= read -r l; do
    echo "KCST $l" > $K 2>/dev/null
    sleep 0.3
done

echo "KCST done $(date)" > $K 2>/dev/null
exit 0
