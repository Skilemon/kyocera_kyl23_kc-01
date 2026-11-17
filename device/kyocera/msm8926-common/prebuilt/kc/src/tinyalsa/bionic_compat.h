/*
 * bionic_compat.h -- the four lines of glue that let unmodified upstream
 * tinyalsa source build against a desktop gcc and still run on this phone.
 *
 * The library has to keep libc symbols *undefined* and declare DT_NEEDED
 * libc.so (bionic), not libc.so.6 (glibc).  See build.sh for how the link is
 * arranged.  Two things in the headers still leak host-specific names:
 *
 *   errno   glibc defines it as (*__errno_location()), bionic as (*__errno()).
 *           Left alone, the .so would carry an undefined __errno_location and
 *           fail to load with "cannot locate symbol".
 *
 *   stderr / fprintf
 *           bionic has no `stderr` object to link against from a library built
 *           this way, and a HAL writing to stdio goes nowhere anyway.  The
 *           error text still lands in pcm->error, which is what the HAL reads
 *           with pcm_get_error(); the fprintf calls only duplicate it.
 *
 * Everything else -- open, ioctl, mmap, poll, snprintf, strerror, calloc --
 * has the same name in both libcs and needs no help.
 */
#ifndef KC_BIONIC_COMPAT_H
#define KC_BIONIC_COMPAT_H

#ifdef KC_TARGET_BIONIC

#undef errno
extern int *__errno(void);
#define errno (*__errno())

#undef stderr
#define stderr ((void *)0)

#undef fprintf
#define fprintf(stream, ...) ((void)(stream))

#endif /* KC_TARGET_BIONIC */

#endif /* KC_BIONIC_COMPAT_H */
