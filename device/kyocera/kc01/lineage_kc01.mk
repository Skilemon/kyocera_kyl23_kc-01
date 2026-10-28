#
# Copyright (C) 2026 The LineageOS Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#

$(call inherit-product, device/kyocera/kc01/device.mk)

# Discard inherited values and use our own anyway
PRODUCT_NAME := lineage_kc01
PRODUCT_DEVICE := kc01
PRODUCT_BRAND := Kyocera
PRODUCT_MODEL := KC-01 (miraie KYL23)
PRODUCT_MANUFACTURER := Kyocera

PRODUCT_BUILD_PROP_OVERRIDES += \
    TARGET_DEVICE=KC-01 \
    BUILD_FINGERPRINT=Kyocera/KC-01/KC-01:4.4.4/102.0.1e20/102.0.1e20:user/release-keys \
    PRIVATE_BUILD_DESC="KC-01-user 4.4.4 102.0.1e20 release-keys"
