#
# TWRP/Omni product makefile - Kyocera KC-01 / miraie KYL23
#

PRODUCT_DEVICE := kc01
PRODUCT_NAME := omni_kc01
PRODUCT_BRAND := Kyocera
PRODUCT_MODEL := KC-01 (miraie KYL23)
PRODUCT_MANUFACTURER := Kyocera

# Inherit device config
$(call inherit-product, $(DEVICE_PATH)/device.mk)

# TWRP flags
TW_THEME := portrait_hdpi
RECOVERY_SDCARD_ON_DATA := true
BOARD_HAS_NO_REAL_SDCARD := false
TW_DEFAULT_EXTERNAL_STORAGE := true
RECOVERY_GRAPHICS_USE_LINELENGTH := true
TW_NO_REBOOT_BOOTLOADER := true
TW_INCLUDE_CRYPTO := true
TW_BRIGHTNESS_PATH := /sys/class/leds/lcd-backlight/brightness
TW_MAX_BRIGHTNESS := 255
TW_NO_SCREEN_TIMEOUT := true
TARGET_RECOVERY_QCOM_RTC_FIX := true
TW_HAS_DOWNLOAD_MODE := false
