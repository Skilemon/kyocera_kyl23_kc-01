#
# Board configuration - miraie KYL23 (2016 stock, 201.x)
#
# Everything shared with the other msm8926 Kyocera device lives in
# device/kyocera/msm8926-common/BoardConfigCommon.mk.
#

include device/kyocera/msm8926-common/BoardConfigCommon.mk

# ------------------------------------------------------------------ kernel
# Only used when KYOCERA_BUILD_KERNEL=true.  The kernel tree itself is NOT in
# this repo - CI clones the LineageOS msm8226 base and lays kernel-overlay/
# on top of it.  See BoardConfigCommon.mk for why the prebuilt stock kernel
# is the default.
ifeq ($(KYOCERA_BUILD_KERNEL),true)
TARGET_KERNEL_SOURCE := kernel/kyocera/kyl23
TARGET_KERNEL_CONFIG := msm8926-kyocera_defconfig
endif

# -------------------------------------------------------------------- disk
TARGET_RECOVERY_FSTAB := device/kyocera/msm8926-common/recovery.fstab
