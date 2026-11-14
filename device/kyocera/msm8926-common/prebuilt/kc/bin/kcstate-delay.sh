#!/system/bin/sh
# Second kcstate pass: by the time the framework has been up for two minutes
# WifiHW has already given up on the supplicant and audioserver has crashed at
# least once, so the report shows the failure instead of the attempt.
sleep 120
exec /vendor/bin/kcstate.sh
