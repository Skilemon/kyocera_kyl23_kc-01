#
# Board configuration - KYV36 / KC-01 (2015 stock, 102.x)
#
# Everything shared with the other msm8926 Kyocera device lives in
# device/kyocera/msm8926-common/BoardConfigCommon.mk.
#

include device/kyocera/msm8926-common/BoardConfigCommon.mk

# -------------------------------------------------------------------- disk
# TARGET_RECOVERY_FSTAB is set in BoardConfigCommon.mk, which picks between the
# TWRP and the LineageOS fstab by product name.  Do not set it here: an
# unconditional assignment would undo that choice.
