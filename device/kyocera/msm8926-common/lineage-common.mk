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

# ------------------------------------------------------------- boot animation
#
# Point the build at the stock 4.4 animation instead of letting vendor/cm
# generate one.  bootanimation/Android.mk reads
#
#     ifeq ($(TARGET_BOOTANIMATION),)
#       TARGET_BOOTANIMATION := $(TARGET_GENERATED_BOOTANIMATION)
#     endif
#
# so anything non-empty here skips generate-bootanimation.sh, ImageMagick and
# bootanimation.tar entirely, and `cp $(TARGET_BOOTANIMATION) $@` installs the
# file verbatim into system/media.  What this tree wants is the animation the
# phone shipped with: 540x960, a single JPEG, fps 1, `p 0 0` loop, copied out
# of the stock system image.
#
# The generated path was actively harmful.  Until TARGET_SCREEN_WIDTH/HEIGHT
# were set (BoardConfigCommon.mk), the generator produced a desc.txt whose
# first line was ` 60`, bootanimation's sscanf saw one field instead of three,
# fps stayed 0, and movie() divided by it about 90 ms after eglInitialize.
# The workflow's "Verify the package" step has been failing on exactly that
# file since fix76 -- it was the only thing standing between a build and a
# phone stuck on the bootloader splash.
TARGET_BOOTANIMATION := $(LINEAGE_COMMON_PATH)/prebuilt/media/bootanimation.zip

# AOSP telephony base first, so vendor/cm/config/common_full_phone.mk
# (inherited by the per-device product makefile) can override it.
$(call inherit-product, $(SRC_TARGET_DIR)/product/aosp_base_telephony.mk)

# The 4.4.4 blobs, extracted by tools/blobs/extract.py.  Fetched by the
# workflow -- 74 MB of proprietary binaries do not belong in this repository.
$(call inherit-product, vendor/kyocera/msm8926-common/msm8926-common-vendor.mk)

# ------------------------------------------------------- HAL shadowing
# msm8926-common-vendor.mk copies the stock 4.4 HALs into
# $(TARGET_COPY_OUT_VENDOR)/lib/hw.  hw_get_module() walks /vendor/lib/hw
# before /system/lib/hw, so every one of them shadows the 7.1 build of the
# same HAL that system/bt and hardware/qcom/display just produced.  Three of
# those blobs cannot work against this ROM and are filtered out here so the
# loader falls back to /system/lib/hw:
#
#   bluetooth.default.so  the 4.4 blob wants AudioTrack::write(void const*,
#       unsigned int); 7.1 only has the (void const*, size_t, bool) overload,
#       so dlopen stops on "cannot locate symbol _ZN7android10AudioTrack5write-
#       EPKvj" and BluetoothServiceJni reports "No Bluetooth Library found" --
#       Bluetooth cannot be switched on, ever.  The 7.1 build in /system/lib/hw
#       is the Fluoride stack and asks for the correct symbol.
#
#   hwcomposer.msm8226.so, gralloc.msm8226.so  the 4.4 pair (103 KB / 18 KB)
#       and the 7.1 pair (141 KB / 26 KB) are not interchangeable: mixing them
#       leaves SurfaceFlinger with a composer it cannot queue buffers to, and
#       the panel stays on the boot splash.  The 7.1 pair is what the display
#       HAL in hardware/qcom/display was built for.
#
# Everything else in /vendor/lib/hw (camera, audio.primary, lights, sensors,
# gps, keystore.qcom ...) has no 7.1 counterpart in this tree and is correct
# as the stock blob.
PRODUCT_COPY_FILES := $(filter-out \
    vendor/kyocera/msm8926-common/proprietary/vendor/lib/hw/bluetooth.default.so:% \
    vendor/kyocera/msm8926-common/proprietary/vendor/lib/hw/hwcomposer.msm8226.so:% \
    vendor/kyocera/msm8926-common/proprietary/vendor/lib/hw/gralloc.msm8226.so:%, \
    $(PRODUCT_COPY_FILES))

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

# No /adb_keys in the ramdisk.  adbd used to pick it up before it looked at
# /data/misc/adb/adb_keys (key_paths[] in adb_auth_client.cpp), which made every
# unit reachable with one private key and no confirmation -- a backdoor, not a
# feature.  Authorisation now goes through the normal path: the dialog on the
# device, or whatever the user has already approved in /data/misc/adb/adb_keys.

# Everything here mirrors the stock build.prop.  Duplicating a few of them in
# system.prop would be harmless but confusing, so these stay in one place.
# Every value here is a single word by construction -- anything with a space in
# it has to go into system.prop instead, see the telephony note below.
PRODUCT_PROPERTY_OVERRIDES += \
    ro.board.platform=msm8226 \
    ro.opengles.version=196608 \
    ro.sf.lcd_density=240 \
    persist.hwc.mdpcomp.enable=true

# --------------------------------------------------------------- telephony
# rild comes from the stock qcril blob, not from AOSP's reference RIL.  Its two
# properties live in system.prop, not here, and that is not a style choice:
# PRODUCT_PROPERTY_OVERRIDES is a whitespace-separated list of key=value words,
# so a value containing a space cannot be expressed in it at all.  Written here
# as `rild.libargs=-d /dev/smd0` it shipped as `rild.libargs=-d`, with /dev/smd0
# silently dropped off the end; backslash-escaping the space does not help,
# because make splits on the space after the expansion, not before it.
#
# What that cost: rild handed qcril one argument fewer than the stock
# build.prop does (RIL_Init argc 4 instead of 5).  The RIL still came up --
# registration state, UIM, SMS and data all answered -- but
# RIL_REQUEST_BASEBAND_VERSION returned GENERIC_FAILURE 14 ms after it was sent,
# on every boot, and Settings showed "Baseband version: Unknown" because the
# telephony stack only writes gsm.version.baseband when that request succeeds.

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
KC_BINS := kcboot kcfuse.sh kc_bootanim.sh kcstate.sh kcwifi \
           kccam.sh kcssr.sh kcstate-delay.sh kcstate-boot.sh kcadsp.sh \
           kcshut.sh kctail.sh kchalt.sh kcsensor.sh kcprox
KC_LIBS := libkccabi.so libkcabi.so libkchwc.so

PRODUCT_COPY_FILES += \
    $(LINEAGE_COMMON_PATH)/rootdir/etc/init/kyl23-extra.rc:system/etc/init/kyl23-extra.rc \
    $(KC_PREBUILT)/kcfix.sh:system/etc/kcfix.sh \
    $(KC_PREBUILT)/kcbt.sh:system/etc/kcbt.sh \
    $(KC_PREBUILT)/kcbtinit.sh:system/etc/kcbtinit.sh

# The two stock Bluetooth tools.  They are what programs the WCNSS Bluetooth
# core's NV (BD_ADDR, reference clock, clock sharing) over /dev/smd3; 7.1 has no
# equivalent, and without them the controller answers HCI_Read_BD_ADDR with
# 00:00:00:00:5A:AD -- see docs/DEVICE_NOTES.md §16.  hci_qcomm_init needs the
# QMI client libraries and libbtnv.so, all already in the vendor blob set.
KC_BTTOOLS := btnvtool hci_qcomm_init

PRODUCT_COPY_FILES += \
    $(foreach f,$(KC_BTTOOLS),$(KC_PREBUILT)/bin/$(f):system/bin/$(f))

PRODUCT_COPY_FILES += \
    $(foreach f,$(KC_BINS),$(KC_PREBUILT)/bin/$(f):$(TARGET_COPY_OUT_VENDOR)/bin/$(f))

PRODUCT_COPY_FILES += \
    $(foreach f,$(KC_LIBS),$(KC_PREBUILT)/lib/$(f):$(TARGET_COPY_OUT_VENDOR)/lib/$(f))
