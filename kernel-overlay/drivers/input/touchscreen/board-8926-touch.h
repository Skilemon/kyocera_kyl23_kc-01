/*
 * This software is contributed or developed by KYOCERA Corporation.
 * (C) 2012 KYOCERA Corporation
 * (C) 2013 KYOCERA Corporation
 * (C) 2014 KYOCERA Corporation
 *
 * arch/arm/mach-msm/board-8926-touch.h
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License version 2 and
 * only version 2 as published by the Free Software Foundation.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
 * 02110-1301, USA.
 *
*/
#ifndef __ARCH_ARM_MACH_MSM_BOARD_MSM8926_TOUCH_H
#define __ARCH_ARM_MACH_MSM_BOARD_MSM8926_TOUCH_H

#ifdef CONFIG_TOUCHSCREEN_ATMEL_MXT_KC
#include <linux/kernel.h>
#include <linux/gpio.h>
//#include <linux/i2c/atmel_mxt_kc.h>
#include "kc_ts.h"

#define MXT_TS_RESET_GPIO	16
#define MXT_TS_GPIO_IRQ		17

#define MXT_PANEL_WIDTH		960
#define MXT_PANEL_HEIGHT	540

#define MXT_BOARD_INFO		I2C_BOARD_INFO("mXT224S", 0x94 >> 1)

static inline int mxt_init_hw(void)
{
	int rc;

	rc = gpio_request(MXT_TS_GPIO_IRQ, "mxt_ts_irq_gpio");
	if (rc) {
		pr_err("%s: unable to request mxt_ts_irq gpio [%d]\n"
						, __func__, MXT_TS_GPIO_IRQ);
		goto err_irq_gpio_req;
	}

	rc = gpio_direction_input(MXT_TS_GPIO_IRQ);
	if (rc) {
		pr_err("%s: unable to set_direction for mxt_ts_irq gpio [%d]\n"
						, __func__, MXT_TS_GPIO_IRQ);
		goto err_irq_gpio_set;
	}

	rc = gpio_request(MXT_TS_RESET_GPIO, "mxt_reset_gpio");
	if (rc) {
		pr_err("%s: unable to request mxt_reset gpio [%d]\n"
						, __func__, MXT_TS_RESET_GPIO);
		goto err_reset_gpio_req;
	}

	rc = gpio_direction_output(MXT_TS_RESET_GPIO, 0);
	if (rc) {
		pr_err("%s: unable to set_direction for mxt_reset gpio [%d]\n"
						, __func__, MXT_TS_RESET_GPIO);
		goto err_reset_gpio_set;
	}

	return 0;

err_reset_gpio_set:
	gpio_free(MXT_TS_RESET_GPIO);
err_reset_gpio_req:
err_irq_gpio_set:
	gpio_free(MXT_TS_GPIO_IRQ);
err_irq_gpio_req:
	return rc;
}

static inline int mxt_reset_hw(void)
{
	KC_TS_DEV_DBG("%s: start\n",__func__);
	gpio_set_value(MXT_TS_RESET_GPIO, 0);
	usleep_range(1000, 1000);
	gpio_set_value(MXT_TS_RESET_GPIO, 1);
	KC_TS_DEV_DBG("%s: end\n",__func__);

	return 0;
}

static inline int mxt_shutdown_hw(void)
{
	gpio_set_value(MXT_TS_RESET_GPIO, 0);
	usleep_range(1000, 1000);

	return 0;
}

#endif /* CONFIG_TOUCHSCREEN_ATMEL_MXT_KC */
#endif /* __ARCH_ARM_MACH_MSM_BOARD_MSM8926_TOUCH_H */
