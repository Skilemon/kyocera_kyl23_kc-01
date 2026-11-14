#!/system/bin/sh
#
# kyl23: start the boot animation from a directory where the adreno driver's
# hardcoded GLES path actually resolves.
#
# The prebuilt EGL blob (libEGL_adreno.so) builds its GLES client library name
# as "egl/libGLESv2_adreno.so" -- a *relative* path.  dlopen() with a slash in
# the name does not search LD_LIBRARY_PATH and does not search /vendor/lib; it
# resolves against the current directory, which for an init service is "/".
# The driver therefore fails with
#
#   Adreno-GSL: os_lib_map error: dlopen failed:
#               library "egl/libGLESv2_adreno.so" not found
#   Adreno-EGL: <eglCreateClientApiContext:2230>: Unable to fetch GL functions
#
# and bootanimation never draws a single frame (black screen, no logo).
# chdir() to /vendor/lib makes that relative path land on the real library.
#
cd /vendor/lib || exit 1
export LD_LIBRARY_PATH=/vendor/lib/egl:/vendor/lib:/system/lib
exec /system/bin/bootanimation
