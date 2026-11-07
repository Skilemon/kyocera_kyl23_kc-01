#
# Product fragment shared by the two Kyocera msm8926 codenames.
#
# Kept apart from msm8926-common.mk on purpose: that file is inherited by the
# omni_* products the TWRP workflow builds, and a recovery build runs against
# the minimal TWRP manifest, which has no device/qcom tree and no vendor blobs.
# Splitting the two means neither build ever evaluates a makefile it cannot
# resolve.
#
# Note that device/qcom/common is *not* inherited here.  On cm-14.1 that
# repository has no product makefile at all -- it is picked up through its own
# Android.mk, which only runs when msm8226 appears in QCOM_BOARD_PLATFORMS
# (set in BoardConfigCommon.mk).  A `$(call inherit-product,
# device/qcom/common/common.mk)` looks right and fails at lunch with "no such
# file".
#

# Set here rather than reused from BoardConfigCommon.mk: the build reads the
# product makefiles *before* the board config (envsetup.mk includes
# product_config.mk at line 131 and board_config.mk at line 157), so
# DEVICE_COMMON_PATH does not exist yet at this point and a reference to it
# would silently expand to the empty string.
LINEAGE_COMMON_PATH := device/kyocera/msm8926-common

# AOSP telephony base first, so vendor/cm/config/common_full_phone.mk
# (inherited by the per-device product makefile) can override it.
$(call inherit-product, $(SRC_TARGET_DIR)/product/aosp_base_telephony.mk)

# The 4.4.4 blobs, extracted by tools/blobs/extract.py.  Fetched by the
# workflow -- 74 MB of proprietary binaries do not belong in this repository.
$(call inherit-product, vendor/kyocera/msm8926-common/msm8926-common-vendor.mk)

PRODUCT_BRAND := Kyocera
PRODUCT_MANUFACTURER := Kyocera
PRODUCT_PLATFORM := msm8226

# ------------------------------------------------------------------ runtime
# 7.1's first-stage init mounts /system using the fstab, which it looks for as
# /vendor/etc/fstab.<hardware> and, failing that, /fstab.<hardware> in the
# ramdisk.  The stock image kept a copy in the ramdisk root for the same reason,
# so both destinations are filled -- a missing fstab is not a warning, it stops
# the boot before anything can be logged.  On a device with no vendor partition
# TARGET_COPY_OUT_VENDOR resolves to system/vendor; writing "vendor/..." here
# would put the file in out/.../vendor and leave it out of system.img entirely.
PRODUCT_COPY_FILES += \
    $(LINEAGE_COMMON_PATH)/rootdir/etc/fstab.qcom:$(TARGET_COPY_OUT_VENDOR)/etc/fstab.qcom \
    $(LINEAGE_COMMON_PATH)/rootdir/etc/fstab.qcom:root/fstab.qcom

# Everything here mirrors the stock build.prop.  Duplicating a few of them in
# system.prop would be harmless but confusing, so these stay in one place.
PRODUCT_PROPERTY_OVERRIDES += \
    ro.board.platform=msm8226 \
    ro.opengles.version=196608 \
    ro.sf.lcd_density=240 \
    persist.hwc.mdpcomp.enable=true

# --------------------------------------------------------------- telephony
# rild comes from the stock qcril blob, not from AOSP's reference RIL.  These
# two properties are how libhardware_legacy finds and execs it.
PRODUCT_PROPERTY_OVERRIDES += \
    rild.libpath=/vendor/lib/libril-qc-qmi-1.so \
    rild.libargs=-d /dev/smd0 \
    ro.telephony.default_network=8

# ------------------------------------------------------------------- audio
PRODUCT_PROPERTY_OVERRIDES += \
    ro.qc.sdk.audio.ssr=false \
    ro.qc.sdk.audio.fluencetype=none \
    persist.audio.fluence.voicecall=false \
    persist.audio.fluence.voicerec=false \
    persist.audio.fluence.speaker=false \
    persist.audio.handset.mic=analog

# ---------------------------------------------------------------- packages
# Nothing Kyocera ships in its own /system/app is carried over: the ROM brings
# its own launcher, dialer and camera.  Everything else the device needs
# arrives as a prebuilt file through msm8926-common-vendor.mk, not as a
# package.
