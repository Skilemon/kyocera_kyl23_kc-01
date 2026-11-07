#
# Product makefiles - KYV36 / KC-01 (2015 stock, 102.x)
#

PRODUCT_MAKEFILES := \
    $(LOCAL_DIR)/omni_kc01.mk \
    $(LOCAL_DIR)/lineage.mk

COMMON_LUNCH_CHOICES := \
    omni_kc01-eng \
    omni_kc01-userdebug \
    lineage_kc01-eng \
    lineage_kc01-userdebug
