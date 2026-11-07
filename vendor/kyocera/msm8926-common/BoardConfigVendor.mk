#
# Board level configuration for the vendor blobs.
#
# The file exists because BoardConfigCommon.mk includes it, following the
# LineageOS convention that a device's board configuration and its proprietary
# files are kept in separate trees.  This vendor tree needs nothing extra:
# the 4.4 blobs are all prebuilt libraries and binaries, none of them carries
# a board flag the build has to know about.
#
# Kept in git even though it is almost empty -- extract.py regenerates
# msm8926-common-vendor.mk and proprietary-files.txt, but never this file.
#
