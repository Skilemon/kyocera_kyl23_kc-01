#
# LineageOS product - miraie KYL23 (2016 stock, 201.x)
#
# This target is a placeholder for the planned ROM work. It is NOT
# usable yet: no vendor blobs are wired up and no msm8926 device tree
# (hardware/qcom, device/qcom/common) is pinned.
#

$(call inherit-product, device/kyocera/kyl23/device.mk)

PRODUCT_NAME := lineage_kyl23
PRODUCT_DEVICE := kyl23
PRODUCT_MODEL := miraie KYL23

PRODUCT_BUILD_PROP_OVERRIDES += \
    TARGET_DEVICE=KYL23 \
    BUILD_FINGERPRINT=Kyocera/KYL23/KYL23:4.4.4/201.1.0a20/201.1.0a20:user/release-keys
PRIVATE_BUILD_DESC="KYL23-user 4.4.4 201.1.0a20 release-keys"
