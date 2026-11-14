#!/system/bin/sh
#
# kccam.sh -- put the camera timeline where a dump can actually reach it.
#
# Preview works; the shutter does not.  Pressing the button brings up "cannot
# connect to the camera" within half a second, the app then wedges in onPause,
# and ten seconds later it is destroyed and killed.  Nothing that explains that
# survived the last dump, for two reasons:
#
#   * the camera HAL writes ~20 lines per preview frame, so every rotating
#     logcat file on the phone is full of "preview norm prev[640*480]" within
#     seconds and the rows that matter are rotated out;
#   * the dump only ever returns the first 20 MB of /cache, and the log files
#     are written past that.
#
# So mirror the interesting rows into the kernel log, which a dump always
# carries in full: the camera service/client state changes, the app's own
# error text ("Camera error", "Cannot connect"), the shutter path, any
# AndroidRuntime crash and the ANR.  A dozen lines per shutter press cannot
# flood the kernel ring.
#
# The last session said this much and no more:
#
#   08:35:06.203  take_picture
#   08:35:06.818  cb message type 24576 not enabled!    <- JPEG callback dropped
#   08:35:06.842  App trying to use insecure INPUT_FEATURE_NO_INPUT_CHANNEL
#   08:35:10.652  stop_preview                          <- 4 s of nothing
#   08:35:11.026  Activity pause timeout
#   08:35:21.273  Activity destroy timeout
#   08:35:22.905  AndroidRuntime: BottomBar#onMeasure() did not set the
#                 measured dimension                          <- "camera stopped"
#
# i.e. the HAL never handed the JPEG back and the app gave up.  What is missing
# is the framework's side of that (Camera2Client / CameraAgent) and the exact
# text the app showed, which is what this now keeps.
#
K=/dev/kmsg

say() {
    echo "KCCAM $*" > $K 2>/dev/null
}

say "start pid=$$"

# Prove the mirror is alive even in a session where the camera is never opened:
# without this line "no KCCAM output" is ambiguous between "nothing happened"
# and "the script never ran".
( while true; do sleep 300; echo "KCCAM alive $(date '+%H:%M')" > $K 2>/dev/null; done ) &

exec /system/bin/logcat -v time -b main -b system -b crash 2>/dev/null \
    -s CameraService:V Camera2Client:V Camera3Device:V CameraModule:V \
       CameraAgent:V CameraActivity:V Camera:V QCamera2HWI:V \
       mm-camera-intf:V AndroidRuntime:E ActivityManager:W am_anr:V \
       am_crash:V am_proc_died:V \
    | while IFS= read -r l; do
        case "$l" in
            *take_picture*|*takePicture*|*TAKE_PICTURE*|*snapshot*|\
            *start_preview*|*stop_preview*|*mm_camera_open*|*openCamera*|\
            *"Camera error"*|*"Cannot connect"*|*"cannot connect"*|\
            *"Camera service is unavailable"*|*onError*|*ErrorCallback*|\
            *"Failed to"*|*disconnect*|*"not enabled"*|\
            *"has died"*|*"ANR in"*|*"not responding"*|\
            *"Activity pause timeout"*|*"Activity destroy timeout"*|\
            *"FATAL EXCEPTION"*|*"did not set the measured"*|\
            *"java.lang"*|*"CameraDevice"*|*"CaptureRequest"*)
                say "$l"
                ;;
        esac
    done
