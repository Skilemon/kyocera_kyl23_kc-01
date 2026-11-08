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
# The image is built around prebuilt/kernel, a zImage compiled from Kyocera's
# own GPL 3.4.0 source (see kernel-patches/); the factory zImage it replaced
# is archived in prebuilt/stock/ for rollback.  Only the self-built one loads
# modules, and the image needs exactly one of them (kc_wp.ko).
#
# Nothing here compiles a kernel, and nothing should: this repo carries no
# kernel source, and the TWRP build tree has no rule that would consume one
# (its build/core/tasks/kernel.mk is not included by main.mk), so a
# TARGET_KERNEL_SOURCE would have no consumer.  Building a kernel is a manual
# job, documented in README.md and docs/DEVICE_NOTES.md.
TARGET_PREBUILT_KERNEL := $(DEVICE_COMMON_PATH)/prebuilt/kernel

BOARD_KERNEL_BASE := 0x00000000
BOARD_KERNEL_PAGESIZE := 2048
BOARD_KERNEL_CMDLINE := console=ttyHSL0,115200,n8 no_console_suspend=1 androidboot.console=ttyHSL0 androidboot.hardware=qcom user_debug=31 msm_rtb.filter=0x37

# SELinux is permissive for now, and deliberately so.
#
# The kernel is built with CONFIG_SECURITY_SELINUX=y, so init enforces unless
# told otherwise, and enforcement here would stop the boot in the first second:
# the device has exactly one policy addition (sepolicy/te/placeholder.te) while
# the vendor tree ships a dozen Kyocera daemons with no domains of their own,
# plus two partitions (/sysprop, /pstore) no other msm8226 device has.  An
# enforcing boot would be a stream of avc denials against services that then
# die, and the phone would never reach the launcher.
#
# Permissive keeps every denial in the log, which is where the policy has to be
# written from anyway.  Flip this to "enforcing" once `dmesg | grep avc` is
# quiet during a full boot, a camera session and a call.
BOARD_KERNEL_CMDLINE += androidboot.selinux=permissive
BOARD_MKBOOTIMG_ARGS := --ramdisk_offset 0x01000000 --second_offset 0x00f00000 --tags_offset 0x00000100

# The device tree is appended to the image as a Qualcomm QCDT blob.  It is
# shipped prebuilt (prebuilt/stock/dtb-kyl23.img) and copied into place either
# by dt_image.mk or by Android.mk, depending on the tree.  Do not regenerate
# it: the stock table has 40 board=8 entries pointing at eight distinct DTBs,
# and collapsing that to one DTB makes aboot hand the kernel a tree for the
# wrong SoC (logo, then reboot after ~3s).
#
# BOARD_KERNEL_PREBUILT_DT means two incompatible things depending on which
# build tree reads it, and both trees have to be satisfied because the same
# device tree feeds LineageOS and TWRP:
#
#   cm-14.1 (vendor/cm)   empty  -> define a rule that runs dtbToolCM
#                         non-empty -> copy that file to dt.img
#     The value is used as a prerequisite:
#       $(INSTALLED_DTIMAGE_TARGET): $(BOARD_KERNEL_PREBUILT_DT) | $(ACP)
#     so a literal "true" asks ninja for a file named "true" and dies with
#     `ninja: error: 'true', needed by 'dt.img', missing and no known rule`.
#
#   omni-7.1 (TWRP)       "true" -> skip dt_image.mk entirely
#                         anything else -> define the dtbToolCM rule
#     tested with `ifneq ($(strip $(BOARD_KERNEL_PREBUILT_DT)),true)`, so a
#     path here is *not* treated as prebuilt - omni overwrites our rule with
#     one that wants `out/host/linux-x86/bin/dtbToolCM`, which the recovery
#     tree never builds.
#
# Hence: a path for LineageOS, the word "true" for anything else.  In the
# omni case Android.mk supplies the copy rule, guarded by the same test, so
# exactly one of the two trees defines dt.img and neither warns about
# overriding the other.
ifneq ($(filter lineage_%,$(TARGET_PRODUCT)),)
BOARD_KERNEL_PREBUILT_DT := $(DEVICE_COMMON_PATH)/prebuilt/stock/dtb-kyl23.img
else
BOARD_KERNEL_PREBUILT_DT := true
endif
BOARD_KERNEL_SEPARATED_DT := true
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

# Two fstabs, because seven's releasetools only reads the unified format and
# TWRP only reads the flags= one.  Its version 1 branch is not usable either:
# common.py builds Partition() there without the `context` argument the class
# requires, so it raises TypeError on the first line.  Same variable, so pick
# by product; omni (TWRP) is everything that is not lineage.
#
# Without this the build dies at 99%, in make_recovery_patch:
#
#   ValueError: malformed recovery.fstab line: "/boot  emmc
#   /dev/block/platform/msm_sdcc.1/by-name/boot  flags=backup=1;flashimg=1"
#
# because a version 2 parser wants five columns and that line has four.
ifneq ($(filter lineage_%,$(TARGET_PRODUCT)),)
TARGET_RECOVERY_FSTAB := $(DEVICE_COMMON_PATH)/recovery-lineage.fstab
endif
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


# ============================================================ full-ROM build
#
# Everything above serves the TWRP build: it compiles bootable/recovery against
# a prebuilt kernel and nothing else.  A LineageOS 14.1 build reads the same
# file and needs a great deal more, which is what follows.
#
# None of it disturbs the recovery build.  The variables either have no
# consumer in a recovery-only tree, or they are assigned here to the value the
# ROM wants while recovery keeps the one it already had -- the few that overlap
# are called out where they do.

# --------------------------------------------------------------- identity
# The seller flashed KC-01's system onto a KYL23, and the bootloader carries
# no reliable model string, so the assert has to accept both codenames and
# both marketing names.
TARGET_OTA_ASSERT_DEVICE := kyl23,kc01,KYL23,KC01,KYV36

TARGET_NO_BOOTLOADER := true
BOARD_USES_QCOM_HARDWARE := true

# device/qcom/common only builds anything when the platform appears in this
# list -- its Android.mk is wrapped in a filter on QCOM_BOARD_PLATFORMS.  Left
# unset, the power HAL, the qcom init scripts and the recovery extensions all
# silently disappear, which looks like a dozen unrelated build failures later.
QCOM_BOARD_PLATFORMS += msm8226

# The device runs qcril from the stock image, which is the CAF flavour of RIL
# rather than the AOSP reference implementation.
TARGET_RIL_VARIANT := caf

# --------------------------------------------------------------- properties
TARGET_SYSTEM_PROP := $(DEVICE_COMMON_PATH)/system.prop

# ------------------------------------------------------------------ kernel
# Same prebuilt zImage as recovery (see the kernel section above): 3.4.0, built
# from Kyocera's own GPL drop.  A ROM build would otherwise look for
# TARGET_KERNEL_SOURCE and fail, because this tree has no kernel.
BOARD_KERNEL_IMAGE_NAME := zImage

# ---------------------------------------------------------------- bluetooth
# bluedroid reads its build-time configuration from this header.
BOARD_BLUETOOTH_BDROID_BUILDCFG_INCLUDE_DIR := $(DEVICE_COMMON_PATH)/bluetooth

# --------------------------------------------------------------------- ANT
BOARD_ANT_WIRELESS_DEVICE := "qualcomm-smd"

# ---------------------------------------------------------------- sepolicy
# device/qcom/sepolicy carries the Qualcomm-wide types (qmi, sensors, thermal)
# that every msm device needs on top of what AOSP ships.
-include device/qcom/sepolicy/sepolicy.mk
BOARD_SEPOLICY_DIRS += $(DEVICE_COMMON_PATH)/sepolicy

# ------------------------------------------------------- vendor partitions
# The blobs were extracted from the 4.4.4 image by tools/blobs/extract.py into
# vendor/kyocera/msm8926-common.  Inheriting the vendor makefile here is what
# pulls in its copy rules; the directory itself is fetched by the workflow,
# because 74 MB of proprietary binaries do not belong in this repository.
-include vendor/kyocera/msm8926-common/BoardConfigVendor.mk

# ---------------------------------------------------------------- wifi (rom)
# In 4.4 the module sat behind a symlink at /system/lib/modules/wlan.ko.  In a
# 7.1 tree the modules live under /vendor, and the symlink is gone, so the
# path is the real file.
WIFI_DRIVER_MODULE_PATH := "/vendor/lib/modules/pronto/pronto_wlan.ko"
BOARD_HAS_QCOM_WLAN_SDK := true

# -------------------------------------------------------------- dexpreopt
# Boot-image-only dexpreopt keeps the first boot short without spending an
# hour optimising every preinstalled app.
ifeq ($(HOST_OS),linux)
  ifneq ($(TARGET_BUILD_VARIANT),eng)
    ifeq ($(WITH_DEXPREOPT),)
      WITH_DEXPREOPT := true
      WITH_DEXPREOPT_BOOT_IMG_ONLY := true
    endif
  endif
endif

