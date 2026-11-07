#
# LineageOS product - KYV36 / KC-01 (2015 stock, 102.x)
#
# This target is a placeholder for the planned ROM work. It is NOT
# usable yet: no vendor blobs are wired up and no msm8926 device tree
# (hardware/qcom, device/qcom/common) is pinned.
#

$(call inherit-product, device/kyocera/kc01/device.mk)

PRODUCT_NAME := lineage_kc01
PRODUCT_DEVICE := kc01
PRODUCT_MODEL := KC-01

PRODUCT_BUILD_PROP_OVERRIDES += \
    TARGET_DEVICE=KC-01 \
    BUILD_FINGERPRINT=Kyocera/KC-01/KC-01:4.4.4/102.0.1e20/102.0.1e20:user/release-keys
PRIVATE_BUILD_DESC="KC-01-user 4.4.4 102.0.1e20 release-keys"
