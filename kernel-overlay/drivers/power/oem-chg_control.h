/*
 * This software is contributed or developed by KYOCERA Corporation.
 * (C) 2014 KYOCERA Corporation
 */
/*
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License version 2 and
 * only version 2 as published by the Free Software Foundation.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 */
#ifndef OEM_CHG_COMTROL_H
#define OEM_CHG_COMTROL_H

#include <linux/power_supply.h>
#include <linux/qpnp/qpnp-adc.h>

#define CHG_WAKE_LOCK_TIMEOUT_MS	(2000)

#define CHG_ERR_TIME_SEC		(8 * 60 * 60)

#define PMA_EOC_HOLD_TIME_MS	(100)

#define BATT_VOLT_POWER_ON_OK	(3600 * 1000)
#define BATT_VOLT_POWER_ON_NG	(3500 * 1000)
#define BATT_VOLT_ERR_CHG_OFF	(4400 * 1000)

#define BATT_REMOVAL_CHECK_TIME	50

#define LIMIT_CHG_ON_TIME	(15 * 1000)
#define LIMIT_CHG_OFF_TIME	(20 * 1000)

#define BATT_VOLT_LIMIT_CHG_ON		(3800 * 1000)
#define BATT_VOLT_LIMIT_CHG_OFF		(3500 * 1000)
#define BATT_VOLT_W_CHG_LIMIT_CHG_ON	(3700 * 1000)

#define FACTORY_TEMP_CHG_OFF		(150 * 10) //(95 * 10)
#define FACTORY_TEMP_LIMIT_CHG_ON	(150 * 10) //(90 * 10)

#define BATT_TEMP_HOT_CHG_OFF		(55 * 10)
#define BATT_TEMP_HOT_CHG_ON		(53 * 10)
#define BATT_TEMP_COLD_CHG_OFF		(0)
#define BATT_TEMP_COLD_CHG_ON		(2 * 10)
#define BATT_TEMP_LIMIT_ON			(150 * 10) //(45 * 10)
#define BATT_TEMP_LIMIT_OFF			(150 * 10) //(43 * 10)

#define CAM_TEMP_TALK_LIMIT_ON		(150 * 10) //(35 * 10)
#define CAM_TEMP_TALK_LIMIT_OFF		(150 * 10) //(31 * 10)
#define CAM_TEMP_DATA_LIMIT_ON		(150 * 10) //(35 * 10)
#define CAM_TEMP_DATA_LIMIT_OFF		(150 * 10) //(31 * 10)
#define CAM_TEMP_W_CHG_LIMIT_ON		(150 * 10) //(-450)
#define CAM_TEMP_W_CHG_LIMIT_OFF	(150 * 10) //(-450)

#define BOARD_TEMP_TALK_LIMIT_ON	(150 * 10) //(40 * 10)
#define BOARD_TEMP_TALK_LIMIT_OFF	(150 * 10) //(36 * 10)
#define BOARD_TEMP_DATA_LIMIT_ON	(150 * 10) //(40 * 10)
#define BOARD_TEMP_DATA_LIMIT_OFF	(150 * 10) //(36 * 10)
#define BOARD_TEMP_W_CHG_LIMIT_ON	(150 * 10) //(45 * 10)
#define BOARD_TEMP_W_CHG_LIMIT_OFF	(150 * 10) //(43 * 10)

#define PMA_TEMP_NORM				(150 * 10) //(44 * 10)
#define PMA_TEMP_HOT				(150 * 10) //(46 * 10)
#define PMA_TEMP_HOT_EOC			(150 * 10) //(55 * 10)
#define PMA_IMAX_UA_TEMP_NORM		(900 * 1000)
#define PMA_IMAX_UA_TEMP_HOT		(500 * 1000)
#define PMA_IMAX_UA_RF_LIMIT		(500 * 1000)

#define GPIO_PMA_I2C_POWER		74
#define CHG_DNAND_CMD			18
#define CHG_DNAND_PMA_UPDATE_FW	159
#define CHG_DNAND_PMA_FW_VER	30
#define PMA_UPDATE_FW_WAIT_CNT	5

#define CHG_DNAND_PMA_RXID	32
#define PMA_UNIQUE_ID_0		0xC4
#define PMA_UNIQUE_ID_1		0x21
#define PMA_UNIQUE_ID_2		0xC8
#define PMA_RXID_SIZE		6

#define BATT_SOC_LIMIT_OFF		90

typedef enum {
	OEM_CHG_ST_IDLE,
	OEM_CHG_ST_FAST,
	OEM_CHG_ST_FULL,
	OEM_CHG_ST_LIMIT,
	OEM_CHG_ST_ERR_BATT_TEMP,
	OEM_CHG_ST_ERR_BATT_VOLT,
	OEM_CHG_ST_ERR_TIME_OVER,
	OEM_CHG_ST_ERR_CHARGER,
	OEM_CHG_ST_ERR_THERMAL_CTRL,
	OEM_CHG_ST_INVALID
} oem_chg_state_type;

enum oem_chg_volt_status {
	OEM_ST_VOLT_LOW = 0,
	OEM_ST_VOLT_NORM,
	OEM_ST_VOLT_HIGH
};

enum oem_chg_temp_status {
	OEM_ST_TEMP_NORM = 0,
	OEM_ST_TEMP_LIMIT,
	OEM_ST_TEMP_STOP
};

enum oem_chg_pma_update_fw_status {
	OEM_PMA_UPDATE_FW_INVALID = 0,
	OEM_PMA_UPDATE_FW_ENABLE,
	OEM_PMA_UPDATE_FW_OK,
	OEM_PMA_UPDATE_FW_NG
};

extern void oem_chg_control_init(void);

extern int oem_chg_control(void);

extern int oem_chg_get_batt_property(enum power_supply_property psp);
extern void oem_chg_stop_charging(void);

extern void oem_chg_set_rf_request(int req);

extern int oem_chg_get_current_batt_status(void);

extern int oem_chg_get_current_batt_health(void);

extern int oem_chg_get_current_batt_voltage(void);

extern int oem_chg_get_current_capacity(void);

extern int oem_chg_get_current_batt_temp(void);

extern int oem_chg_get_current_pa_therm(void);

extern int oem_chg_get_current_camera_therm(void);

extern int oem_chg_get_current_board_therm(void);

extern int oem_chg_get_current_chg_connect(void);

extern int oem_chg_get_current_iusb_max(void);

extern int oem_chg_get_current_temp_status(void);

extern int oem_chg_get_current_volt_status(void);

extern void oem_chg_ps_changed_batt(void);

extern int oem_chg_batt_fet_ctrl(int enable);

extern int oem_chg_buck_ctrl(int disable);

extern int oem_chg_vadc_read(enum qpnp_vadc_channels channel,
				struct qpnp_vadc_result *result);

extern void oem_batt_led_init(void);

extern void oem_chg_set_pma_eoc(bool value);

extern oem_chg_state_type oem_get_current_chg_state(void);

/**
 * oem_chg_uim_status_check - uim status check in hkadc_monitor
 *
 */
void oem_chg_uim_status_check(void);
/**
 * oem_chg_set_uim_status_fix_parm - when uim status is fixed, set ibat_max & vdd_max
 *
 */
void oem_chg_set_uim_status_fix_parm(void);
void oem_uim_smem_init(void);
bool oem_is_uim_dete(void);

extern int oem_chg_is_thermal_limitation(void);

unsigned int oem_vddmax_get(void);
void oem_clear_oem_chg_vbatdet_change_flag(void);

extern u8 oem_chg_get_bat_fet_status(void);
#endif
