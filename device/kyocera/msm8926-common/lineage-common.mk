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

# The two files init looks for by name.  7.1's own init.rc only does
# `import /init.${ro.hardware}.rc` and leaves the mounting to the board file --
# there is no fallback, so a missing init.qcom.rc means no mount_all, no
# /system, and a phone that sits on the boot logo with nothing in the log.
# ueventd.cpp looks for /ueventd.${ro.hardware}.rc in the same way.
PRODUCT_COPY_FILES += \
    $(LINEAGE_COMMON_PATH)/rootdir/init.qcom.rc:root/init.qcom.rc \
    $(LINEAGE_COMMON_PATH)/rootdir/ueventd.qcom.rc:root/ueventd.qcom.rc

# adbd will not hand out a shell until it has an authorised key, and the dialog
# that authorises one needs a screen that works -- precisely what is missing
# when the boot hangs.  adbd checks /adb_keys in the ramdisk before it looks at
# /data/misc/adb/adb_keys (key_paths[] in adb_auth_client.cpp), so shipping a
# known public key here makes the device reachable from a black screen.
#
# This is a bring-up crutch: anyone holding the matching private key gets a
# root shell.  Delete both this rule and rootdir/adb_keys before the image is
# used for anything real.
PRODUCT_COPY_FILES += \
    $(LINEAGE_COMMON_PATH)/rootdir/adb_keys:root/adb_keys

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

# 7.1 ships its own wpa_supplicant, and this ROM has to use it.  The stock 4.4
# binary that has been standing in its place speaks the 4.4 ctrl_iface
# dialect: its command table holds the bare string "LIST_NETWORKS" compared
# with strcmp, so the framework's "LIST_NETWORKS LAST_ID=-1" comes back as
# UNKNOWN COMMAND, and the network ids it hands out never line up with the
# ones the framework remembers.  What that looks like on the device is a
# Wi-Fi list showing saved networks the supplicant does not have, a password
# prompt after every toggle, and a 375-byte wpa_supplicant.conf with no
# network block left in it.
#
# The module is LOCAL_MODULE_TAGS := optional, so nothing pulls it in unless
# it is named here.  BOARD_WPA_SUPPLICANT_PRIVATE_LIB is already set to
# lib_driver_cmd_qcwcn in BoardConfigCommon.mk, which makes the build link the
# QCA driver-command shim instead of the ANDROID_LIB_STUB no-op; that shim is
# what carries DRIVER SETSUSPENDMODE to the pronto driver, and it needs
# hardware/qcom/wlan present in the manifest (see the workflow).
PRODUCT_PACKAGES += \
    wpa_supplicant

# ------------------------------------------------------- board init, and the
# helpers it starts
#
# kyl23-extra.rc is where this port actually lives.  Everything the 7.1
# framework needs and the 4.4 blob set cannot provide -- the modem EFS server,
# the prima loader, the supplicant, the ADSP bring-up, the LD_PRELOAD that
# back-fills the dropped 4.4 symbols into every vendor binary -- is started
# from, or configured in, that one file.  Without it in system/etc/init the ROM
# boots and then does nothing: no baseband, no Wi-Fi, no sound.
#
# The helpers are prebuilt binaries and scripts, not build products; they are
# the glue nothing else on this device ships.  PRODUCT_COPY_FILES installs
# everything 0644, so the rc sets the execute bit itself in post-fs-data, before
# the first exec.  (The images used during bring-up were assembled by hand and
# already carried 0755, which is why this only matters for a ROM built here.)
KC_PREBUILT := $(LINEAGE_COMMON_PATH)/prebuilt/kc
KC_BINS := kcboot kcfuse.sh kcbtnled kc_bootanim.sh kcstate.sh kcwifi \
           kccam.sh kcssr.sh kcstate-delay.sh kcstate-boot.sh kcadsp.sh \
           kcshut.sh kctail.sh kchalt.sh
KC_LIBS := libkccabi.so libkcabi.so libkchwc.so

PRODUCT_COPY_FILES += \
    $(LINEAGE_COMMON_PATH)/rootdir/etc/init/kyl23-extra.rc:system/etc/init/kyl23-extra.rc \
    $(KC_PREBUILT)/kcfix.sh:system/etc/kcfix.sh

PRODUCT_COPY_FILES += \
    $(foreach f,$(KC_BINS),$(KC_PREBUILT)/bin/$(f):$(TARGET_COPY_OUT_VENDOR)/bin/$(f))

PRODUCT_COPY_FILES += \
    $(foreach f,$(KC_LIBS),$(KC_PREBUILT)/lib/$(f):$(TARGET_COPY_OUT_VENDOR)/lib/$(f))
