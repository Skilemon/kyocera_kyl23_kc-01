/*
 * This software is contributed or developed by KYOCERA Corporation.
 * (C) 2012 KYOCERA Corporation
 * (C) 2013 KYOCERA Corporation
 * (C) 2014 KYOCERA Corporation
 *
 * include/linux/i2c/atmel_mxt_kc.h
 *
 * Copyright (C) 2010 Samsung Electronics Co.Ltd
 * Author: Joonyoung Shim <jy0922.shim@samsung.com>
 * Copyright (c) 2011-2012, Code Aurora Forum. All rights reserved.
 *
 * This program is free software; you can redistribute  it and/or modify it
 * under  the terms of  the GNU General  Public License as published by the
 * Free Software Foundation;  either version 2 of the  License, or (at your
 * option) any later version.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
 * 02110-1301, USA.
 */

#ifndef __LINUX_ATMEL_MXT_KC_H
#define __LINUX_ATMEL_MXT_KC_H

#include <linux/types.h>

/* Orient */
#define MXT_NORMAL		0x0
#define MXT_DIAGONAL		0x1
#define MXT_HORIZONTAL_FLIP	0x2
#define MXT_ROTATED_90_COUNTER	0x3
#define MXT_VERTICAL_FLIP	0x4
#define MXT_ROTATED_90		0x5
#define MXT_ROTATED_180		0x6
#define MXT_DIAGONAL_COUNTER	0x7

/* Touchscreen absolute values */
#define T7_BACKUP_SIZE		2

/* Define for diag */
#define MXT_DIAG_DATA_SIZE		130
#define MXT_DIAG_NUM_PAGE		6

enum mxt_err_type {
	MXT_ERR_CFGERR,
	MXT_ERR_RESET,
	MXT_ERR_MISBEHAVING,
	MXT_ERR_ESD,
	MXT_ERR_MAX,
};

struct mxt_object {
	u8 type;
	u16 start_address;
	u8 size;
	u8 instances;
	u8 num_report_ids;

	/* to map object and message */
	u8 max_reportid;
	bool report_enable;
};

struct mxt_info {
	u8 family_id;
	u8 variant_id;
	u8 version;
	u8 build;
	u8 matrix_xsize;
	u8 matrix_ysize;
	u8 object_num;
};

enum mxt_device_state { INIT, APPMODE, BOOTLOADER };

/* The platform data for the Atmel maXTouch touchscreen driver */
struct kc_ts_platform_data {
	unsigned int	x_size;
	unsigned int	y_size;
	unsigned long	irqflags;
	int		irq_gpio;
	int		reset_gpio;
	int		(*init_hw) (void);
	int		(*reset_hw) (void);
	int		(*shutdown) (void);
	unsigned char	orient;
};

struct kc_ts_vendor_data {
	struct i2c_client	*client;
	struct mxt_object	*object_table;
	struct mxt_info		info;
	u8			t7_data[T7_BACKUP_SIZE];
	enum mxt_device_state	state;
	u16			t7_start_addr;
	u16			max_o_size;
	u8			err_cnt[MXT_ERR_MAX];
};

#endif /* __LINUX_ATMEL_MXT_KC_H */
