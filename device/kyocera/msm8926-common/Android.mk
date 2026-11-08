#
# Android.mk - device-tree glue the generic build does not provide
#
# Two things are missing when a device ships a prebuilt kernel and a prebuilt
# Qualcomm QCDT blob instead of building either.  Both of them stop ninja with
# "missing and no known rule to make it", so both are fixed here.
#
#   1. dt.img
#   2. $(KERNEL_HEADERS)
#
LOCAL_PATH := $(call my-dir)

# ---------------------------------------------------------------------- dt.img
#
# BOARD_KERNEL_SEPARATED_DT makes the boot/recovery image consume
# $(PRODUCT_OUT)/dt.img, but nothing produces it: BOARD_KERNEL_PREBUILT_DT told
# build/core/tasks/dt_image.mk to keep its own rule (dtbToolCM) from being
# defined, because that tool needs a kernel build tree we do not have.
#
# So the blob is shipped prebuilt, byte for byte as it came off the device.
# That is not laziness, it is the only thing that boots:
#
#   * the stock table has 40 entries for board=8, pointing at EIGHT distinct
#     DTBs.  Regenerating it from a single DTB (what a naive dtbTool run does)
#     makes aboot hand the kernel a device tree for a different SoC - the logo
#     still appears, then the phone reboots after about three seconds.
#   * entry layout is six 32-bit words, 24 bytes:
#         msm_id, board_id, variant_id, soc_rev, offset, size
#     Note msm_id comes FIRST.  Reading it as the board id shifts every field
#     by one and produces a table that looks plausible and never matches.
#
# This device's key is (msm_id=200, board=8, variant=0, soc_rev=0x10001),
# which must resolve to the DTB at offset 0xec800.
#
# Define the rule only for the tree that will not define it itself, i.e. when
# BoardConfig set BOARD_KERNEL_PREBUILT_DT to the literal "true" (omni, TWRP).
# cm-14.1 gets a path there and copies the blob from dt_image.mk instead.  See
# the long comment in BoardConfigCommon.mk; this test is the exact complement
# of omni's `ifneq ($(strip $(BOARD_KERNEL_PREBUILT_DT)),true)`, so exactly one
# of the two trees defines dt.img and neither warns about overriding the other.
ifeq ($(strip $(BOARD_KERNEL_SEPARATED_DT)),true)
ifeq ($(strip $(BOARD_KERNEL_PREBUILT_DT)),true)

INSTALLED_DTIMAGE_TARGET := $(PRODUCT_OUT)/dt.img
QCDT_PREBUILT           := $(LOCAL_PATH)/prebuilt/stock/dtb-kyl23.img

$(INSTALLED_DTIMAGE_TARGET): $(QCDT_PREBUILT)
	@echo "target QCDT (prebuilt): $@"
	$(hide) cp -f $< $@

droidcore: $(INSTALLED_DTIMAGE_TARGET)

.PHONY: dtimage
dtimage: $(INSTALLED_DTIMAGE_TARGET)

endif
endif

# ------------------------------------------------------------ kernel headers
#
# The kernel is a prebuilt zImage, so scripts/headers_install never runs and
# $(KERNEL_HEADERS) - $(TARGET_OUT_INTERMEDIATES)/KERNEL_OBJ/usr/include -
# never comes into existence.  system/core/sdcard still asks for it, as an
# include path and as a prerequisite, and the build dies before compiling a
# single line of anything:
#
#   ninja: error: '.../obj/KERNEL_OBJ/usr', needed by
#   '.../libsdcard_intermediates/sdcard.o', missing and no known rule to make it
#
# Pointing TARGET_KERNEL_SOURCE at a real tree would satisfy it the proper way,
# but there is no kernel in this repo to point at (see README.md: the zImage is
# built by hand from Kyocera's GPL drop), and dragging 2 GB of kernel source
# into CI to generate headers nothing else reads is not a trade worth making.
#
# So the directory is created empty.  That is enough for both uses: the -I is
# additive and everything sdcard.c needs comes from bionic's copy of the uapi
# headers, which is searched anyway.  No other module in a cm-14.1 tree pulls
# in $(KERNEL_HEADERS) as a prerequisite.
#
# Both the parent and the leaf get a rule: ninja names whichever one the
# dependant happened to record, and complaining about a missing parent is just
# as fatal as complaining about a missing leaf.
KERNEL_HEADERS_STUB := $(TARGET_OUT_INTERMEDIATES)/KERNEL_OBJ/usr

$(KERNEL_HEADERS_STUB):
	@mkdir -p $(KERNEL_HEADERS_STUB)/include

$(KERNEL_HEADERS_STUB)/include: $(KERNEL_HEADERS_STUB)
	@mkdir -p $@
