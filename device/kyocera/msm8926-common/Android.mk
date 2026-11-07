#
# Android.mk - place the Qualcomm QCDT blob (dt.img) where the build expects it
#
# BOARD_KERNEL_SEPARATED_DT makes the recovery/boot image consume
# $(PRODUCT_OUT)/dt.img, but nothing in an AOSP 7.1 tree produces it - and
# BOARD_KERNEL_PREBUILT_DT already told build/core/tasks/dt_image.mk to keep
# its own rule (dtbToolCM) from being defined, because that tool needs a kernel
# build tree we do not have.
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
LOCAL_PATH := $(call my-dir)

ifeq ($(strip $(BOARD_KERNEL_SEPARATED_DT)),true)

INSTALLED_DTIMAGE_TARGET := $(PRODUCT_OUT)/dt.img
QCDT_PREBUILT           := $(LOCAL_PATH)/prebuilt/stock/dtb-kyl23.img

$(INSTALLED_DTIMAGE_TARGET): $(QCDT_PREBUILT)
	@echo "target QCDT (prebuilt): $@"
	$(hide) cp -f $< $@

droidcore: $(INSTALLED_DTIMAGE_TARGET)

.PHONY: dtimage
dtimage: $(INSTALLED_DTIMAGE_TARGET)

endif
