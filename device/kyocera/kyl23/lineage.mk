#
# LineageOS 14.1 product - miraie KYL23 (2016 stock, 201.x)
#
# The seller flashed KC-01's system onto this handset, so the image on it
# reports the other model.  The hardware is the 2016 one, and so is the modem
# firmware (MPSS.DI.2.0.1.c9, built 2016-08-10), which is what decides the RIL
# behaviour.  Hence the codename here is kyl23 and not kc01.
#
# No build fingerprint override on purpose: pinning the 4.4.4 string would make
# Build.VERSION.RELEASE and the fingerprint disagree, and nothing on this
# device needs the factory identity any more.  What must stay correct is
# TARGET_DEVICE, which the OTA script and the recovery assert read.
#

$(call inherit-product, device/kyocera/msm8926-common/lineage-common.mk)
$(call inherit-product, vendor/cm/config/common_full_phone.mk)

PRODUCT_NAME := lineage_kyl23
PRODUCT_DEVICE := kyl23
PRODUCT_MODEL := miraie KYL23

PRODUCT_BUILD_PROP_OVERRIDES += \
    TARGET_DEVICE=KYL23
