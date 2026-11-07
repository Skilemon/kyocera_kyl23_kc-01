#
# Common product fragment - Kyocera msm8926 family (KC-01 / KYL23)
#
# Device makefiles inherit this first, then override what is model
# specific (PRODUCT_MODEL, build fingerprint, DTB selection).
#

DEVICE_COMMON_PATH := device/kyocera/msm8926-common

PRODUCT_BRAND := Kyocera
PRODUCT_MANUFACTURER := Kyocera
PRODUCT_PLATFORM := msm8226

# ------------------------------------------------------------- TWRP flags
# 720x1280 panel, so portrait_hdpi is the correct theme resolution.
TW_THEME := portrait_hdpi
TW_BRIGHTNESS_PATH := /sys/class/leds/lcd-backlight/brightness
TW_MAX_BRIGHTNESS := 255
TW_NO_SCREEN_TIMEOUT := true
TW_NO_REBOOT_BOOTLOADER := true
TW_HAS_DOWNLOAD_MODE := false
TW_DEFAULT_EXTERNAL_STORAGE := true
RECOVERY_SDCARD_ON_DATA := true
RECOVERY_GRAPHICS_USE_LINELENGTH := true

# Encryption: the stock userdata is ext4 with
# encryptable=/persist/udf, i.e. the legacy Qualcomm qseecom path.
# Keep this off until the TWRP build is known good - enabling it pulls in
# an extra set of crypto binaries and is a common build breaker.
TW_INCLUDE_CRYPTO := false

# ------------------------------------------------------------- packages
# bootable/recovery declares its binary with LOCAL_MODULE_TAGS := optional,
# so it is built only when something asks for it by name.  Without these the
# build still succeeds and produces a ramdisk full of busybox applets and
# theme images, but no /sbin/recovery and no /init - an image that boots to a
# blank screen.
#
# adbd and healthd are the two services init.rc declares but that live
# outside bootable/recovery:
#   service adbd    /sbin/adbd          <- adb shell / sideload
#   service healthd /sbin/healthd       <- charging animation when off
PRODUCT_PACKAGES += \
    recovery \
    init \
    adbd \
    healthd

# ------------------------------------------------------------- properties
PRODUCT_PROPERTY_OVERRIDES += \
    ro.product.brand=Kyocera \
    dalvik.vm.heapsize=256m
