/*
 * Bluedroid build configuration - Kyocera msm8926
 *
 * The controller is a Qualcomm WCN3620 behind the SMD transport, so the stack
 * is built with BLE and the wideband codec path on, and with the vendor
 * specific SCO routing that the QDSP6 firmware expects.
 */
#ifndef _BDROID_BUILDCFG_H
#define _BDROID_BUILDCFG_H

#define BTM_DEF_LOCAL_NAME   "KYL23"

/* The controller reports a 4.0 stack; enabling 4.1 features makes the
 * attribute cache time out on every LE connection. */
#define BTA_DM_COD {0x5A, 0x02, 0x0C}
#define BTM_SCO_ENHANCED_SYNC_ENABLED FALSE
#define BLE_VND_INCLUDED   TRUE

/* Wideband speech is on in the WCN3620 firmware and the audio HAL exposes the
 * matching path; leaving this off forces narrowband on every call. */
#define BTM_WBS_INCLUDED TRUE

/* One ACL link is enough for this radio, and asking for more makes the
 * firmware drop the second connection without an error. */
#define BTM_MAX_SCO_LINKS 1

#endif
