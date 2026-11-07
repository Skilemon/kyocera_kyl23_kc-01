#
# Common board configuration - Kyocera msm8926 family
#   KC-01 (KYV36) and miraie KYL23
#
# Every kernel and partition value below was read out of a dumped stock
# boot.img / recovery.img.  They are not guesses - if you change one,
# re-dump the header first.
#
#   stock recovery.img header
#     magic        ANDROID!
#     page_size    2048
#     kernel_size  5808608   kernel_addr  0x00008000
#     ramdisk_size 1224393   ramdisk_addr 0x01000000
#     second_size  0         second_addr  0x00f00000
#     tags_addr    0x00000100
#     dt_size      5179392
#

DEVICE_COMMON_PATH := device/kyocera/msm8926-common

# ---------------------------------------------------------------- platform
TARGET_BOARD_PLATFORM := msm8226
TARGET_BOARD_PLATFORM_GPU := qcom-adreno305
TARGET_BOOTLOADER_BOARD_NAME := MSM8226
BOARD_VENDOR := kyocera-qcom

# ------------------------------------------------------------ architecture
TARGET_ARCH := arm
TARGET_ARCH_VARIANT := armv7-a-neon
TARGET_CPU_ABI := armeabi-v7a
TARGET_CPU_ABI2 := armeabi
TARGET_CPU_VARIANT := krait
TARGET_CPU_MEMCPY_BASE_OPT_DISABLE := true

# ------------------------------------------------------------------ kernel
#
# By default the image is built around the STOCK kernel taken out of the
# factory recovery.img.  It is the only kernel that has been proven to boot
# on this hardware - the whole recovery pipeline was validated on a real
# device with it, so a build made from this repo works without first having
# to make a kernel build succeed.
#
# Set KYOCERA_BUILD_KERNEL=true to compile the kernel from source instead.
# That path is wired up (kernel-overlay/ + msm8926-kyocera_defconfig) but has
# not yet been proven to boot; see docs/DEVICE_NOTES.md.
KYOCERA_BUILD_KERNEL ?= false

TARGET_KERNEL_ARCH := arm
TARGET_KERNEL_HEADER_ARCH := arm
TARGET_KERNEL_CROSS_COMPILE_PREFIX := arm-linux-androideabi-
KERNEL_TOOLCHAIN := $(ANDROID_BUILD_TOP)/prebuilts/gcc/linux-x86/arm/arm-linux-androideabi-4.9/bin

ifeq ($(KYOCERA_BUILD_KERNEL),true)
# TARGET_KERNEL_SOURCE / TARGET_KERNEL_CONFIG come from the device makefile.
else
TARGET_PREBUILT_KERNEL := $(DEVICE_COMMON_PATH)/prebuilt/kernel
endif

BOARD_KERNEL_BASE := 0x00000000
BOARD_KERNEL_PAGESIZE := 2048
BOARD_KERNEL_CMDLINE := console=ttyHSL0,115200,n8 no_console_suspend=1 androidboot.console=ttyHSL0 androidboot.hardware=qcom user_debug=31 msm_rtb.filter=0x37
BOARD_MKBOOTIMG_ARGS := --ramdisk_offset 0x01000000 --second_offset 0x00f00000 --tags_offset 0x00000100

# The device tree is appended to the image as a Qualcomm QCDT blob.  It is
# shipped prebuilt (prebuilt/stock/dtb-kyl23.img) and merely copied into place
# by Android.mk.  Do not regenerate it: the stock table has 40 board=8 entries
# pointing at eight distinct DTBs, and collapsing that to one DTB makes aboot
# hand the kernel a tree for the wrong SoC (logo, then reboot after ~3s).
#
# BOARD_KERNEL_PREBUILT_DT stops build/core/tasks/dt_image.mk from defining
# its own dt.img rule.  That rule shells out to $(HOST_OUT)/bin/dtbToolCM and
# reads DTBs out of $(KERNEL_OUT)/arch/arm/boot - neither exists when we build
# around a prebuilt kernel, and ninja fails with "missing and no known rule".
BOARD_KERNEL_SEPARATED_DT := true
BOARD_KERNEL_PREBUILT_DT := true
BOARD_DTBTOOL_ARGS :=

# -------------------------------------------------------------- partitions
# Sizes taken from the live device (/proc/partitions) and from the images
# in the full-partition backup.
BOARD_FLASH_BLOCK_SIZE := 131072
BOARD_BOOTIMAGE_PARTITION_SIZE := 16777216
BOARD_RECOVERYIMAGE_PARTITION_SIZE := 16777216
BOARD_SYSTEMIMAGE_PARTITION_SIZE := 1472179712
BOARD_USERDATAIMAGE_PARTITION_SIZE := 5468165120
BOARD_CACHEIMAGE_PARTITION_SIZE := 480247808
BOARD_CACHEIMAGE_FILE_SYSTEM_TYPE := ext4
BOARD_PERSISTIMAGE_PARTITION_SIZE := 8388608

# ---------------------------------------------------------------- recovery
TARGET_RECOVERY_PIXEL_FORMAT := "RGBX_8888"
TARGET_USERIMAGES_USE_EXT4 := true
TARGET_RECOVERY_FSTAB := $(DEVICE_COMMON_PATH)/recovery.fstab
RECOVERY_FSTAB_VERSION := 2
BOARD_HAS_NO_SELECT_BUTTON := true
BOARD_RECOVERY_SWIPE := true
LZMA_RAMDISK_TARGETS := recovery
TARGET_RECOVERY_QCOM_RTC_FIX := true

# The image produced by `mka recoveryimage` is NOT flashable on this hardware:
# its 7.1 init cannot build the property area on a 3.4 kernel and the phone
# panics ("Attempted to kill init").  tools/image/mkhybrid.py takes the payload out
# of out/.../recovery/root and grafts it onto the stock 4.4.4 ramdisk; the
# LZMA setting above then only affects that intermediate artifact, because
# mkhybrid always repacks the final ramdisk as gzip (this kernel has no
# CONFIG_RD_LZMA).

# ------------------------------------------------------------------ audio
BOARD_USES_ALSA_AUDIO := true
AUDIO_FEATURE_ENABLED_MULTI_VOICE_SESSIONS := true
AUDIO_FEATURE_ENABLED_NEW_SAMPLE_RATE := true

# -------------------------------------------------------------- bluetooth
BOARD_HAVE_BLUETOOTH := true
BOARD_HAVE_BLUETOOTH_QCOM := true
BLUETOOTH_HCI_USE_MCT := true

# ----------------------------------------------------------------- camera
TARGET_HAS_LEGACY_CAMERA_HAL1 := true
USE_DEVICE_SPECIFIC_CAMERA := true

# ---------------------------------------------------------------- charger
BACKLIGHT_PATH := /sys/class/leds/lcd-backlight/brightness
BOARD_CHARGER_ENABLE_SUSPEND := true
BOARD_NO_CHARGER_LED := true

# ---------------------------------------------------------------- display
NUM_FRAMEBUFFER_SURFACE_BUFFERS := 3
TARGET_USES_C2D_COMPOSITION := true
TARGET_USES_ION := true
USE_OPENGL_RENDERER := true
TARGET_PROVIDES_LIBLIGHT := true

# ------------------------------------------------------------- performance
MALLOC_SVELTE := true

# ---------------------------------------------------------------- security
TARGET_SEPOLICY_DIR := msm8226
HAVE_SELINUX := true

# ------------------------------------------------------------------- wifi
BOARD_HAS_QCOM_WLAN := true
BOARD_WLAN_DEVICE := qcwcn
WPA_SUPPLICANT_VERSION := VER_0_8_X
BOARD_WPA_SUPPLICANT_DRIVER := NL80211
BOARD_WPA_SUPPLICANT_PRIVATE_LIB := lib_driver_cmd_qcwcn
BOARD_HOSTAPD_DRIVER := NL80211
BOARD_HOSTAPD_PRIVATE_LIB := lib_driver_cmd_qcwcn
WIFI_DRIVER_MODULE_PATH := "/system/lib/modules/wlan.ko"
WIFI_DRIVER_MODULE_NAME := "wlan"
WIFI_DRIVER_FW_PATH_AP := "apsta"
WIFI_DRIVER_FW_PATH_STA := "sta"
WIFI_DRIVER_FW_PATH_P2P := "p2p"
