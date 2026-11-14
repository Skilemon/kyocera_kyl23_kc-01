#!/system/bin/sh
#
# kctail.sh -- small, rotating, high-signal logcat capture.
#
# kcrec pumps the whole stream into /cache/kl.log but stops at 1 MB, which on
# this ROM is about 75 seconds of output; the file ends long before anything
# interesting happens.  This one keeps a rolling window instead: 192 KB per
# file, five generations, so whatever the phone was doing just before a freeze
# is always on disk.
#
# The tag list is a *whitelist*, and fix30 got it wrong: it included mm-camera
# and QCamera2HWI, which emit about twenty lines per preview frame.  The whole
# 960 KB window filled with "preview norm prev[640*480]" within four seconds,
# so the WiFi off/on cycle and the camera shutter press -- the two things that
# round was supposed to explain -- were pushed out of the ring before the dump.
# The camera's per-frame spam is gone from here; the parts of the camera that
# matter (service, client, activity, errors) stay, and kccam.sh mirrors the
# transitions into the kernel log separately.
#
exec /system/bin/logcat -v time -b main -b system -b crash \
     -f /cache/kc_tail.log -r 192 -n 5 \
     -s ActivityManager:V Watchdog:V AndroidRuntime:V am_anr:V am_crash:V \
        am_proc_died:V am_proc_start:V am_kill:V libc:V chatty:V \
        Zygote:V SystemServer:V ActivityThread:V WindowManager:V \
        AudioService:V AudioFlinger:V audioserver:V audio_hw_primary:V \
        AudioPolicyManager:V AudioSystem:V AudioTrack:V \
        BluetoothAdapterService:V bluedroid:V bt-btif:V \
        BluetoothManagerService:V \
        CameraManagerGlobal:V CameraService:V Camera2Client:V \
        Camera3Device:V CameraActivity:V Camera:V \
        WifiStateMachine:V WifiService:V WifiNative:V WifiMonitor:V \
        WifiConfigManager:V WifiHAL:V wpa_supplicant:V \
        ConnectivityService:V ConnectivityManager:V DhcpClient:V
