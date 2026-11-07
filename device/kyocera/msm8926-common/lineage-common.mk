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
# 7.1's first-stage init reads the fstab from /vendor/etc; the stock one sat in
# the ramdisk root, which is why it is copied rather than imported.  The target
# path is written out instead of using $(TARGET_COPY_OUT_VENDOR): that variable
# is only guaranteed to be set later in the build than this file is evaluated.
PRODUCT_COPY_FILES += \
    $(DEVICE_COMMON_PATH)/rootdir/etc/fstab.qcom:vendor/etc/fstab.qcom

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
