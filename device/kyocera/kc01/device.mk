DEVICE_PATH := device/kyocera/kc01

# Root
PRODUCT_COPY_FILES += \
    $(DEVICE_PATH)/rootdir/init.kc01.rc:root/init.kc01.rc \
    $(DEVICE_PATH)/rootdir/fstab.kc01:root/fstab.kc01 \
    $(DEVICE_PATH)/rootdir/init.kc01.usb.rc:root/init.kc01.usb.rc

# Properties
PRODUCT_PROPERTY_OVERRIDES += \
    ro.product.device=kc01 \
    dalvik.vm.heapsize=256m

# Inherit from proprietary blobs (when present)
# $(call inherit-product, vendor/kyocera/kc01/kc01-vendor.mk)
