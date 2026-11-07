#
# LineageOS 14.1 product - KYV36 / KC-01 (2015 stock, 102.x)
#
# Same board, same blobs, same kernel as kyl23; the difference is the model
# string and the key that the 2015 firmware maps to the camera.  Building both
# from one tree is what makes it possible to flash either and still have a
# phone that identifies itself correctly.
#

$(call inherit-product, device/kyocera/msm8926-common/lineage-common.mk)
$(call inherit-product, vendor/cm/config/common_full_phone.mk)

PRODUCT_NAME := lineage_kc01
PRODUCT_DEVICE := kc01
PRODUCT_MODEL := KC-01

PRODUCT_BUILD_PROP_OVERRIDES += \
    TARGET_DEVICE=KC-01
