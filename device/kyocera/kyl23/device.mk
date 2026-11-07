#
# Device makefile - miraie KYL23 (2016 stock, 201.x)
#

$(call inherit-product, device/kyocera/msm8926-common/msm8926-common.mk)

PRODUCT_DEVICE := kyl23
PRODUCT_MODEL := miraie KYL23
PRODUCT_PROPERTY_OVERRIDES += \
    ro.product.device=kyl23

# NOTE: the stock init/*.rc files in rootdir/ are for building a full ROM,
# not for TWRP - recovery ignores them. They are kept here so a ROM
# bring-up starts from the real Kyocera scripts instead of guesswork, but
# they are deliberately not copied into the recovery image.
