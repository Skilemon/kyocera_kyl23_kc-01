/*
 * This software is contributed or developed by KYOCERA Corporation.
 * (C) 2013 KYOCERA Corporation
 * (C) 2014 KYOCERA Corporation
 *
 * drivers/input/touchscreen/kc_ts.c
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
 */

#include <linux/delay.h>
#include <linux/interrupt.h>
#include <linux/irq.h>
#include <asm/uaccess.h>
#include <linux/module.h>
#include <linux/input/mt.h>
#include <linux/slab.h>
#include <linux/proc_fs.h>
#include <linux/namei.h>
#include <linux/mutex.h>
#include <linux/cdev.h>
#define FEATURE_FACTORY_TEST

#ifdef CONFIG_OF
#include "board-8926-touch.h"
#endif 

struct sysfs_data_{
	char command;
	u16 start_addr;
	u16 size;
} sdata;

/* sysfs ctrl command list */
#ifdef FEATURE_TOUCH_TEST
#define KC_SYSFS_LOG_FS		'l'
#endif /* FEATURE_TOUCH_TEST */
#define KC_SYSFS_KDBGLEVEL	'k'
#define KC_SYSFS_POLLING	'p'
#define KC_SYSFS_WRITE		'w'
#define KC_SYSFS_READ		'r'
#define KC_SYSFS_REFERENCE	'd'
#define KC_SYSFS_CONFIG		'c'
#define KC_SYSFS_STATUS		's'
#define KC_SYSFS_IRQ		'i'
#define KC_SYSFS_NOTICE		'n'

/* Global Variables */
struct ts_diag_type *diag_data;
EXPORT_SYMBOL_GPL(diag_data);
unsigned int ts_event_control = 0;
EXPORT_SYMBOL_GPL(ts_event_control);
unsigned int ts_log_level = 0;
EXPORT_SYMBOL_GPL(ts_log_level);
unsigned int ts_log_file_enable = 0;
EXPORT_SYMBOL_GPL(ts_log_file_enable);
unsigned int ts_esd_recovery = 0;
EXPORT_SYMBOL_GPL(ts_esd_recovery);
unsigned int ts_config_switching = 1;
EXPORT_SYMBOL_GPL(ts_config_switching);
unsigned int ts_error_status = 0;
EXPORT_SYMBOL_GPL(ts_error_status);

static int kc_ts_suspend(struct device *dev);
static int kc_ts_resume(struct device *dev);

static int kc_ts_open(struct inode *inode, struct file *file)
{
	struct kc_ts_data *ts =
		container_of(inode->i_cdev, struct kc_ts_data, device_cdev);
	KC_TS_DEV_DBG("%s() is called.\n", __func__);

	file->private_data = ts;
	return 0;
};

static int kc_ts_release(struct inode *inode, struct file *file)
{
	KC_TS_DEV_DBG("%s() is called.\n", __func__);
	file->private_data = NULL;
	return 0;
};

static long kc_ts_diag_data_start(struct kc_ts_data *ts)
{
	KC_TS_DEV_DBG("%s is called.\n", __func__);
	if (diag_data == NULL) {
		diag_data = kzalloc(sizeof(struct ts_diag_type), GFP_KERNEL);
		if (!diag_data) {
			dev_err(ts->dev, "Failed to allocate memory!\n");
			return -ENOMEM;
		}
		memset(diag_data, 0, sizeof(struct ts_diag_type));
	}

	return 0;
}

static void kc_ts_diag_store(struct kc_ts_data *ts)
{
	struct kc_ts_finger *finger = ts->finger;
	int i;
	int cnt = 0;

	memset(diag_data, 0, sizeof(struct ts_diag_type));
	for (i = 0; i < KC_TS_MAX_FINGER; i++) {
		if (!finger[i].status)
			continue;
		diag_data->ts[i].x = finger[i].x;
		diag_data->ts[i].y = finger[i].y;
		diag_data->ts[i].width = finger[i].area;
		KC_TS_DEV_DBG("%s: touch[%d] x, y, width = %d, %d, %d\n", __func__, i,
						diag_data->ts[i].x, diag_data->ts[i].y, diag_data->ts[i].width);
		cnt++;
	}
	diag_data->diag_count = cnt;
	KC_TS_DEV_DBG("%s: diag_count = %d\n", __func__, diag_data->diag_count);
}

static long kc_ts_diag_data_end(struct kc_ts_data *ts)
{
	KC_TS_DEV_DBG("%s is called.\n", __func__);

	if (diag_data != NULL) {
		kfree(diag_data);
		diag_data = NULL;
	}
	return 0;
}

static long kc_ts_get_property(struct device *dev, unsigned long arg)
{
	struct kc_ts_data *ts = dev_get_drvdata(dev);
	struct ts_nv_data *dp = (struct ts_nv_data *)arg;
	struct ts_config_nv *config_nv;
	enum ts_nv_type nv_type;
	long err = 0;
	size_t size;
	char *str;
	char ver[5];
	char *p;

	KC_TS_DEV_DBG("%s is start\n", __func__);
	err = copy_from_user(&nv_type, (void __user *)&dp->nv_type, sizeof(dp->nv_type));
	if (err){
		err = -EFAULT;
		pr_err("%s: copy_from_user error :nv_type\n", __func__);
		goto done;
	}
	config_nv = &ts->config_nv[nv_type];

	err = copy_from_user(&size, (void __user *)&dp->size, sizeof(size_t));
	if (err){
		err = -EFAULT;
		pr_err("%s: copy_from_user error\n", __func__);
		goto done;
	}
	str = kcalloc(size, sizeof(char), GFP_KERNEL);
	if (!str) {
		pr_err("%s: Failed to allocate memory\n", __func__);
		err = -ENOMEM;
		goto done;
	}
	err = copy_from_user(str, (void __user *)dp->data, size);
	if (err){
		err = -EFAULT;
		pr_err("%s: copy_from_user error\n", __func__);
		goto done;
	}

	mutex_lock(&ts->lock);
	config_nv->size = size / 2 - TS_VER_SIZE - TS_END_CODE;

	memset(ver, '\0', sizeof(ver));
	memcpy(ver, str, 4);
	if(hex2bin((u8 *)&config_nv->ver, ver, 2))
		pr_err("%s:1 hex2bin is error\n",__func__);

	if(config_nv->ver & 0xFF00){
		p = str + 4;
		if(hex2bin(config_nv->data, p, config_nv->size))
			pr_err("%s:2 hex2bin is error\n",__func__);
		pr_notice("%s: type = %d, size = %d\n", __func__, nv_type, size);
	} else
		KC_TS_DEV_DBG("%s property system is disable\n", __func__);

	mutex_unlock(&ts->lock);
	kfree(str);

done:
	return err;
}

static long kc_ts_set_nv(struct kc_ts_data *ts)
{
	u8 *nv = ts->config_nv[TS_CHARGE_CABLE].data;
	long ret = 0;
	long err;

	if (!nv) {
		pr_err("%s: No nv data. Skipping set nv.\n", __func__);
		return 0;
	}

	err = wait_for_completion_interruptible_timeout(&ts->init_done,
			msecs_to_jiffies(5 * MSEC_PER_SEC));

	if (err < 0) {
		pr_err("Error while waiting for device init (%d)!\n", (int)err);
		return -ENXIO;
	} else if (err == 0) {
		pr_err("Timedout while waiting for device init!\n");
		return -ENXIO;
	}

	if (ts->is_enable) {
		disable_irq_nosync(ts->irq);
		ts->is_enable = false;
	}

	ret = (long)ts->tops->check_reg_nv(ts);
	if (ret){
		pr_err("%s: Failed set nv\n",__func__);
		return err;
	}

	if (ts->is_set) {
		pr_notice("%s: NVM set.\n", __func__);
		ret = (long)ts->tops->backup_nv(ts);
		if (ret)
			pr_err("%s: Fail to backup!\n", __func__);
		else
			ts->is_set = false;
	}

	if (!ts->is_enable) {
		enable_irq(ts->irq);
		ts->is_enable = true;
	}

	return ret;
}


static long kc_ts_ioctl(struct file *file, unsigned int cmd,
						unsigned long arg)
{
	struct kc_ts_data *ts = (struct kc_ts_data *)file->private_data;
	struct device *dev = ts->dev;
	long err = 0;
	int val = 0;
#ifdef FEATURE_TOUCH_TEST
	struct ts_log_data log;
#endif

	KC_TS_DEV_DBG("%s() is called.\n", __func__);
	switch (cmd) {
	case IOCTL_SET_CONF_STAT:
		KC_TS_DEV_DBG("%s: IOCTL_SET_CONF_STAT\n", __func__);
		if (ts->irq == -1) {
			if(!ts_error_status){
				dev_err(dev, "driver is abnormal status.\n");
				ts_error_status |= TS_ERR_CHARGE;
			}
			return -1;
		}
		if (!access_ok(VERIFY_READ, (void __user *)arg,
						_IOC_SIZE(cmd))) {
			err = -EFAULT;
			dev_err(dev, "%s: invalid access\n", __func__);
			goto done;
		}

		mutex_lock(&ts->lock);
		err = ts->tops->ioctl(ts, cmd, arg);
		err = ts->tops->calibrate(ts);
		if (err < 0)
			pr_err("%s: mxt_calibrate failed in resume\n", __func__);
		mutex_unlock(&ts->lock);
		break;
	case IOCTL_SET_LOG:
#ifdef FEATURE_TOUCH_TEST
		KC_TS_DEV_DBG("%s: IOCTL_SET_LOG\n", __func__);
		if (!access_ok(VERIFY_READ, (void __user *)arg,
						_IOC_SIZE(cmd))) {
			err = -EFAULT;
			dev_err(dev, "%s: invalid access\n", __func__);
			goto done;
		}

		if (copy_from_user(&log, (void __user *)arg, sizeof(log))) {
			err = -EFAULT;
			dev_err(dev, "%s: copy_from_user error\n", __func__);
			goto done;
		}

		KC_TS_DEV_DBG("mxt_write_log(data, MXT_LOG_DAEMON, &flag)");

		mutex_lock(&ts->lock);
		ts->tops->write_log(ts, KC_TS_LOG_DAEMON, &log);
		mutex_unlock(&ts->lock);
#else
		KC_TS_DEV_DBG("%s: IOCTL_SET_LOG Skip\n", __func__);
#endif
		break;
	case IOCTL_DIAG_START:
		KC_TS_DEV_DBG("%s: IOCTL_DIAG_START\n", __func__);
		if (ts->irq == -1) {
			dev_err(dev, "driver is abnormal status.\n");
			return -1;
		}
		err = kc_ts_diag_data_start(ts);
		break;

	case IOCTL_MULTI_GET:
	case IOCTL_COODINATE_GET:
		KC_TS_DEV_DBG("%s: IOCTL_MULTI_GET\n", __func__);
		KC_TS_DEV_DBG("%s: IOCTL_COODINATE_GET\n", __func__);
		if (ts->irq == -1) {
			dev_err(dev, "driver is abnormal status.\n");
			return -1;
		}
		if (!access_ok(VERIFY_WRITE, (void __user *)arg,
						_IOC_SIZE(cmd))) {
			err = -EFAULT;
			dev_err(dev, "%s: invalid access\n", __func__);
			goto done;
		}
 		if (diag_data != NULL) {
			mutex_lock(&ts->lock);
			kc_ts_diag_store(ts);
			mutex_unlock(&ts->lock);
			err = copy_to_user((void __user *)arg, diag_data,
						sizeof(struct ts_diag_type));
		} else
			dev_info(dev, "Touchscreen Diag not active!\n");

		if (err) {
			dev_err(dev, "%s: copy_to_user error\n", __func__);
			return -EFAULT;
		}
		break;

	case IOCTL_DIAG_END:
		KC_TS_DEV_DBG("%s: IOCTL_DIAG_END\n", __func__);
		if (ts->irq == -1) {
			dev_err(dev, "driver is abnormal status.\n");
			return -1;
		}
		err = kc_ts_diag_data_end(ts);
		break;

	case IOCTL_DIAG_EVENT_CTRL:
		KC_TS_DEV_DBG("%s: IOCTL_DIAG_EVENT_CTRL\n", __func__);
		if (ts->irq == -1) {
			dev_err(dev, "driver is abnormal status.\n");
			return -1;
		}
		if (!access_ok(VERIFY_READ, (void __user *)arg,
						_IOC_SIZE(cmd))) {
			err = -EFAULT;
			dev_err(dev, "%s: invalid access\n", __func__);
			goto done;
		}
		err = copy_from_user(&ts_event_control, (void __user *)arg,
						sizeof(unsigned char));
		if (err){
			dev_err(dev, "%s: copy_from_user error\n", __func__);
			return -EFAULT;
		}
		KC_TS_DEV_DBG("%s: ts_event_control is [%d]\n", __func__
							, ts_event_control);
		break;
	case IOCTL_LOAD_NV:
		KC_TS_DEV_DBG("%s: IOCTL_LOAD_NV\n",__func__);
		if (!access_ok(VERIFY_READ, (void __user *)arg, _IOC_SIZE(cmd))) {
			err = -EFAULT;
			pr_err("%s: invalid access\n", __func__);
			goto done;
		}
		err = kc_ts_get_property(dev, arg);
		break;
	case IOCTL_SET_NV:
		KC_TS_DEV_DBG("%s: IOCTL_SET_NV\n", __func__);
		if (ts->irq == -1) {
			pr_err("%s: driver is abnormal status.\n", __func__);
			return -1;
		}
		mutex_lock(&ts->lock);
		err = kc_ts_set_nv(ts);
		mutex_unlock(&ts->lock);
		break;
	case IOCTL_DIAG_LOG_LEVEL:
		KC_TS_DEV_DBG("%s: IOCTL_DIAG_LOG_LEVEL\n", __func__);
		if (!access_ok(VERIFY_READ, (void __user *)arg,
						_IOC_SIZE(cmd))) {
			err = -EFAULT;
			dev_err(dev, "%s: invalid access\n", __func__);
			goto done;
		}
		err = copy_from_user(&ts_log_level, (void __user *)arg,
						sizeof(unsigned char));
		if (err){
			dev_err(dev, "%s: copy_from_user error\n", __func__);
			return -EFAULT;
		}
		KC_TS_DEV_DBG("%s: ts_log_level is [%d]\n",
						__func__ , ts_log_level);
		break;
	case IOCTL_DIAG_RESET_HW:
		KC_TS_DEV_DBG("%s: IOCTL_DIAG_RESET_HW\n", __func__);
		if (ts->irq == -1) {
			dev_err(dev, "driver is abnormal status.\n");
			return -1;
		}
		mutex_lock(&ts->lock);
		if (ts->pdata->reset_hw)
			ts->pdata->reset_hw();
		mutex_unlock(&ts->lock);
		break;
	case IOCTL_GET_GOLDEN_REFERENCE:
		KC_TS_DEV_DBG("%s: IOCTL_GET_GOLDEN_REFERENCE\n", __func__);
		if (!access_ok(VERIFY_WRITE, (void __user *)arg,
						_IOC_SIZE(cmd))) {
			err = -EFAULT;
			pr_err("%s: invalid access\n", __func__);
			goto done;
		}
		mutex_lock(&ts->lock);
		err = ts->tops->ioctl(ts, cmd, arg);
		mutex_unlock(&ts->lock);
		break;
	case IOCTL_DIAG_GET_C_REFERENCE:
	case IOCTL_DIAG_GET_DELTA:
		KC_TS_DEV_DBG("%s: IOCTL_DIAG_T37_DATA\n", __func__);
		if (ts->irq == -1) {
			dev_err(dev, "driver is abnormal status.\n");
			return -1;
		}

		if (!access_ok(VERIFY_READ, (void __user *)arg,
						_IOC_SIZE(cmd))) {
			err = -EFAULT;
			dev_err(dev, "%s: invalid access\n", __func__);
			goto done;
		}
		mutex_lock(&ts->lock);
		if(ts->is_suspended){
			pr_err("%s Touch is in Sleep\n", __func__);
			err = -1;
			mutex_unlock(&ts->lock);
			goto done;
		}
		err = ts->tops->ioctl(ts, cmd, arg);
		mutex_unlock(&ts->lock);
		break;
	case IOCTL_CHECK_FW:
		err = ts->tops->ioctl(ts, cmd, arg);
		break;
	case IOCTL_GET_INFO:
		KC_TS_DEV_DBG("%s: IOCTL_GET_INFO\n", __func__);
		if (!access_ok(VERIFY_WRITE, (void __user *)arg,
						_IOC_SIZE(cmd))) {
			err = -EFAULT;
			dev_err(dev, "%s: invalid access\n", __func__);
			goto done;
		}
		KC_TS_DEV_DBG("%s: mxt_check_fw\n", __func__);
		mutex_lock(&ts->lock);
		err = ts->tops->ioctl(ts, cmd, arg);
		mutex_unlock(&ts->lock);
		break;
	case IOCTL_DIAG_SELFTEST:
		KC_TS_DEV_DBG("%s: IOCTL_DIAG_SELFTEST\n", __func__);
		if (!access_ok(VERIFY_WRITE, (void __user *)arg,
						_IOC_SIZE(cmd))) {
			err = -EFAULT;
			dev_err(dev, "%s: invalid access\n", __func__);
			goto done;
		}
		mutex_lock(&ts->lock);
		if (ts->irq == -1 || ts->is_suspended == 1){
			pr_err("%s Driver is abnormal or Touch is in Sleep\n", __func__);
			err = -1;
			mutex_unlock(&ts->lock);
			goto done;
		}
		err = ts->tops->ioctl(ts, cmd, arg);
		mutex_unlock(&ts->lock);
		break;
	case IOCTL_DIAG_SUSPEND_RESUME:
		KC_TS_DEV_DBG("%s: IOCTL_DIAG_SUSPEND_RESUME\n", __func__);
		if (ts->irq == -1) {
			dev_err(dev, "driver is abnormal status.\n");
			return -1;
		}
		if (!access_ok(VERIFY_READ, (void __user *)arg,
						_IOC_SIZE(cmd))) {
			err = -EFAULT;
			dev_err(dev, "%s: invalid access\n", __func__);
			goto done;
		}
		err = copy_from_user(&val, (void __user *)arg, sizeof(unsigned char));
		if (err){
			dev_err(dev, "%s: copy_from_user error\n", __func__);
			return -EFAULT;
		}
		KC_TS_DEV_DBG("%s: Request mode = %d  (1:suspend, 2:resume)\n", __func__ , val);
		if(val == 1)
			kc_ts_suspend(ts->dev);
		else if(val == 2)
			kc_ts_resume(ts->dev);
		break;
	default:
		dev_err(dev, "%s: cmd error[%X]\n", __func__, cmd);
		return -EINVAL;
		break;
	}
done:
	return err;
}

irqreturn_t kc_ts_interrupt(int irq, void *dev_id)
{
	struct kc_ts_data *ts = dev_id;

	mutex_lock(&ts->lock);
	ts->release_check = 0;
	ts->tops->interrupt(ts);
	if(!ts->monitoring_flag){
		switch (ts->force_calibration){
		case 0:
			if ((ts->last_touch_finger == 0) &&
				(ts->true_touch == TS_TRUE_TOUCH)){
					KC_TS_DEV_DBG("%s Exit monitoring\n",__func__);
					ts->monitoring_flag = 1;
					ts->tops->write(ts->vdata->client, 0x0228, 0x00);
					ts->tops->write(ts->vdata->client, 0x01DC, 0x01);
			}
			break;
		case 1:
			if(ts->release_check == 1){
				KC_TS_DEV_DBG("%s: Golden route\n",__func__);
				if (ts->calib_wq) {
					cancel_delayed_work_sync(&ts->calib_work);
					flush_workqueue(ts->calib_wq);
				}
				if (ts->calib_wq && !(ts_error_status)) {
					queue_delayed_work(ts->calib_wq, &ts->calib_work,
							   msecs_to_jiffies(50));
				}
			}
			break;
		case 2:
			if (ts->tops->calibrate(ts))
				pr_err("%s: mxt_calibrate failed in resume\n", __func__);
			if (ts->wq) {
				cancel_delayed_work_sync(&ts->esdwork);
				flush_workqueue(ts->wq);
			}
			if (ts->wq && !(ts_error_status)) {
				queue_delayed_work(ts->wq, &ts->esdwork,
						   msecs_to_jiffies(1000));
			}
			break;
		default:
			break;
		}
	}
	mutex_unlock(&ts->lock);

	return IRQ_HANDLED;
}
EXPORT_SYMBOL(kc_ts_interrupt);

#ifdef CONFIG_PM
static int kc_ts_suspend(struct device *dev)
{
	struct kc_ts_data *ts = dev_get_drvdata(dev);
	struct input_dev *input_dev = ts->input_dev;
	int err = 0;

	KC_TS_DEV_DBG("%s: start\n", __func__);
	if (ts->wq) {
		cancel_delayed_work_sync(&ts->esdwork);
		flush_workqueue(ts->wq);
	}

	mutex_lock(&ts->lock);
	if (!input_dev->users) {
		pr_err("%s input_dev->users disable\n", __func__);
		goto done;
	}
	if(ts->is_suspended) {
		pr_notice("%s suspend is true\n", __func__);
		goto done;
	}

	err = ts->tops->power_off(ts);
	if (err < 0) 
		pr_err("%s: failed in suspend process.\n", __func__);
	ts->is_suspended = true;
done:
	mutex_unlock(&ts->lock);
	return err;
}

static int kc_ts_resume(struct device *dev)
{
	struct kc_ts_data *ts = dev_get_drvdata(dev);
	struct input_dev *input_dev = ts->input_dev;
	int err = 0;

	KC_TS_DEV_DBG("%s: start\n", __func__);
	mutex_lock(&ts->lock);
	if (!input_dev->users) {
		pr_err("%s input_dev->users disable\n", __func__);
		goto done;
	}
	if(!ts->is_suspended) {
		pr_notice("%s suspend is false\n", __func__);
		goto done;
	}

	err = ts->tops->power_on(ts);
	if (err < 0) {
		pr_err("%s: failed in resume process.\n", __func__);
		goto done;
	}

	ts->is_suspended = false;
	ts->tops->clear(ts);
	err = ts->tops->calibrate(ts);
	if (err < 0)
		pr_err("%s: mxt_calibrate failed in resume\n", __func__);
	else
		KC_TS_DEV_DBG("%s: mxt_calibrate done.\n", __func__);

	if (ts->wq && !(ts_error_status)) {
		queue_delayed_work(ts->wq, &ts->esdwork,
				   msecs_to_jiffies(ESD_POLLING_TIME));
	}
done:
	mutex_unlock(&ts->lock);
	return err;
}

#if defined(CONFIG_KC_TOUCH_FB)
int fb_notifier_callback(struct notifier_block *self,
				 unsigned long event, void *data)
{
	struct fb_event *evdata = data;
	int *blank;
	struct kc_ts_data *ts =
		container_of(self, struct kc_ts_data, fb_notif);

	if (evdata && evdata->data && event == FB_EVENT_BLANK && ts) {
		blank = evdata->data;
		if (*blank == FB_BLANK_UNBLANK)
			kc_ts_resume(ts->dev);
		else if (*blank == FB_BLANK_POWERDOWN)
			kc_ts_suspend(ts->dev);
	}

	return 0;
}
EXPORT_SYMBOL(fb_notifier_callback);
#elif defined(CONFIG_KC_TOUCH_EARLY_SUSPEND)
void kc_ts_early_suspend(struct early_suspend *h)
{
	struct kc_ts_data *ts = container_of(h, struct kc_ts_data, early_suspend);
	KC_TS_DEV_DBG("%s: is called\n",__func__);
	kc_ts_suspend(ts->dev);
	KC_TS_DEV_DBG("%s has ended.\n",__func__);
}
EXPORT_SYMBOL(kc_ts_early_suspend);

void kc_ts_late_resume(struct early_suspend *h)
{
	struct kc_ts_data *ts = container_of(h, struct kc_ts_data, early_suspend);
	KC_TS_DEV_DBG("%s: is called\n",__func__);
	kc_ts_resume(ts->dev);
	KC_TS_DEV_DBG("%s has ended.\n",__func__);
}
EXPORT_SYMBOL(kc_ts_late_resume);
#endif
#endif /* CONFIG_PM */

void kc_ts_golden_cal(struct work_struct *work)
{
	struct kc_ts_data *ts = container_of(work, struct kc_ts_data, calib_work.work);

	KC_TS_DEV_DBG("%s: is called\n",__func__);

	if (ts->tops->calibrate(ts))
		pr_err("%s: mxt_calibrate failed in resume\n", __func__);

	if (ts->wq) {
		cancel_delayed_work_sync(&ts->esdwork);
		flush_workqueue(ts->wq);
	}
	if (ts->wq && !(ts_error_status)) {
		queue_delayed_work(ts->wq, &ts->esdwork,
				   msecs_to_jiffies(1000));
	}
}

void kc_ts_esd_work(struct work_struct *work)
{
	struct kc_ts_data *ts = container_of(work, struct kc_ts_data, esdwork.work);
	int err = 0;

	if ((!ts_esd_recovery) && mutex_trylock(&ts->lock)) {
		err = ts->tops->esd_proc(ts);

		if((ts->ts_calibrate_cnt == 0) && (ts->true_touch == 0)){
			 KC_TS_DEV_DBG("%s: cal & not touch -> first ESD\n", __func__);
			ts->tops->calibrate(ts);
		}
		mutex_unlock(&ts->lock);
	}

	if (ts->wq && !err) {
		queue_delayed_work(ts->wq, &ts->esdwork,
					msecs_to_jiffies(5000));
	} else {
		ts_error_status |= TS_ERR_DISCONNECTION;
		pr_err("%s: Failed to ESD work!\n", __func__);
	}
}
EXPORT_SYMBOL(kc_ts_esd_work);

static int kc_ts_input_open(struct input_dev *idev)
{
	int err = 0;
	struct kc_ts_data *ts = input_get_drvdata(idev);

	KC_TS_DEV_DBG("%s is start\n", __func__);
	if(!ts){
		pr_err("%s: Error kc_ts_data is found\n",__func__);
		return -1;
	}

	err = wait_for_completion_interruptible_timeout(&ts->init_done,
			msecs_to_jiffies(5 * MSEC_PER_SEC));
	if (err > 0) {
		if (ts->irq != -1) {
			err = ts->tops->input_open(ts);
		} else {
			pr_err("%s: Can't enable irq.\n",__func__);
#ifdef FEATURE_FACTORY_TEST
			err = 0;
#else
			err = -ENXIO;
#endif
		}
	} else if (err < 0) {
		pr_err("%s: Error while waiting for device init (%d)!\n",__func__, err);
		err = -ENXIO;
	} else if (err == 0) {
		pr_err("%s: Timedout while waiting for device init!\n",__func__);
		err = -ENXIO;
	}
	return err;
}

static void kc_ts_input_close(struct input_dev *idev)
{
	struct kc_ts_data *ts = input_get_drvdata(idev);
	if (ts->irq != -1){
		ts->tops->input_close(ts);
	}
}

int ts_ctrl_init(struct kc_ts_data *ts, const struct file_operations *fops)
{
	struct cdev *device_cdev = &ts->device_cdev;
	int device_major = ts->device_major;
	struct class *device_class = ts->device_class;

	dev_t device_t = MKDEV(0, 0);
	struct device *class_dev_t = NULL;
	int ret;

	ret = alloc_chrdev_region(&device_t, 0, 1, "ts_ctrl");
	if (ret)
		goto error;

	device_major = MAJOR(device_t);

	cdev_init(device_cdev, fops);
	device_cdev->owner = THIS_MODULE;
	device_cdev->ops = fops;
	ret = cdev_add(device_cdev, MKDEV(device_major, 0), 1);
	if (ret)
		goto err_unregister_chrdev;

	device_class = class_create(THIS_MODULE, "ts_ctrl");
	if (IS_ERR(device_class)) {
		ret = -1;
		goto err_cleanup_cdev;
	};

	class_dev_t = device_create(device_class, NULL,
		MKDEV(device_major, 0), NULL, "ts_ctrl");
	if (IS_ERR(class_dev_t)) {
		ret = -1;
		goto err_destroy_class;
	}

	return 0;

err_destroy_class:
	class_destroy(device_class);
err_cleanup_cdev:
	cdev_del(device_cdev);
err_unregister_chrdev:
	unregister_chrdev_region(device_t, 1);
error:
	return ret;
}
EXPORT_SYMBOL_GPL(ts_ctrl_init);

int ts_ctrl_exit(struct kc_ts_data *ts)
{
	struct cdev *device_cdev = &ts->device_cdev;
	int device_major = ts->device_major;
	struct class *device_class = ts->device_class;
	dev_t device_t = MKDEV(device_major, 0);

	if (device_class) {
		device_destroy(device_class, MKDEV(device_major, 0));
		class_destroy(device_class);
	}
	if (device_cdev) {
		cdev_del(device_cdev);
		unregister_chrdev_region(device_t, 1);
	}
	return 0;
}
EXPORT_SYMBOL_GPL(ts_ctrl_exit);

const struct file_operations kc_ts_fops = {
	.owner = THIS_MODULE,
	.open = kc_ts_open,
	.unlocked_ioctl = kc_ts_ioctl,
	.release = kc_ts_release,
};

static ssize_t kc_ctrl_store(struct device *dev,
				struct device_attribute *attr,
				const char *buf, size_t count)
{
	struct kc_ts_data *data = dev_get_drvdata(dev);
	const char *p;
	unsigned int val;
	int offset = 0;
	u16 reg_addr;
	struct mxt_object *object;
	int err = 0;
	int last_address;

	switch (buf[0]) {
#ifdef FEATURE_TOUCH_TEST
	case KC_SYSFS_LOG_FS:
		KC_TS_DEV_DBG("%s: KC_SYSFS_LOG_FS\n", __func__);
		sscanf(buf, "%c %x", &sdata.command,
					(unsigned int *) &ts_log_file_enable);
		KC_TS_DEV_DBG("%s: ts_log_file_enable is set to %d\n", __func__ ,
							ts_log_file_enable);
		break;
#endif
	case KC_SYSFS_KDBGLEVEL:
		KC_TS_DEV_DBG("%s: KC_SYSFS_KDBGLEVEL\n", __func__);
		sscanf(buf, "%c %x", &sdata.command,
					(unsigned int *) &ts_log_level);
		KC_TS_DEV_DBG("%s: ts_log_level = %x\n", __func__, ts_log_level);
		break;
	case KC_SYSFS_POLLING:
		KC_TS_DEV_DBG("%s: KC_SYSFS_POLLING\n", __func__);
		sscanf(buf, "%c %x", &sdata.command,
					(unsigned int *) &ts_esd_recovery);
		KC_TS_DEV_DBG("ts_esd_recovery is set to %d\n",
							ts_esd_recovery);
		break;
	case KC_SYSFS_WRITE:
		KC_TS_DEV_DBG("%s: KC_SYSFS_WRITE\n", __func__);
		sscanf(buf, "%c", &sdata.command);
		if(data->ts_sequence <= TS_SEQ_PROBE_IC_NONE){
			pr_err("%s: Touch IC does not exist\n",__func__);
			break;
		}
		p = buf + 1;
		if (sscanf(p, " %x%n", (unsigned int *)&sdata.start_addr,
								&offset) != 1) {
			dev_err(data->dev, "Too short Parameters!\n");
			break;
		}
		p += offset;
		sdata.size = 0;
		KC_TS_DEV_DBG("%s: start_address is [%04X].\n", __func__,
							sdata.start_addr);
		object = data->vdata->object_table + (data->vdata->info.object_num - 1);
		last_address = object->start_address +
				((object->size + 1) *
				 (object->instances + 1)) - 1;
		if (sdata.start_addr > last_address) {
			dev_err(dev, "%s:Invalid start address[%04X]!\n",
						__func__, sdata.start_addr);
			break;
		}
		reg_addr = sdata.start_addr;
		mutex_lock(&data->lock);
		while (sscanf(p, " %x%n", &val, &offset) == 1) {
			data->tops->write(data->vdata->client, reg_addr, (u8)val);
			pr_notice("%s:Write addr=%x, val=%x\n", __func__, reg_addr, (u8)val);
			p += offset;
			reg_addr++;
			if (reg_addr > last_address) {
				dev_err(dev, "%s: Invalid address!\n",
								__func__);
				break;
			}
			sdata.size++;
		}
		mutex_unlock(&data->lock);
		KC_TS_DEV_DBG("%s: write size is [%d].\n", __func__, sdata.size);
		break;
	case KC_SYSFS_READ:
		KC_TS_DEV_DBG("%s: KC_SYSFS_READ\n", __func__);
		if(data->ts_sequence <= TS_SEQ_PROBE_IC_NONE){
			pr_err("%s: Touch IC does not exist\n",__func__);
		}
		sscanf(buf, "%c %x %x", &sdata.command,
			(unsigned int *)&sdata.start_addr,
			(unsigned int *)&sdata.size);
		KC_TS_DEV_DBG("KC_SYSFS_READ: start_addr is [%04X]. "
				"size is [%d].\n", sdata.start_addr, sdata.size);
		break;
	case KC_SYSFS_CONFIG:
		KC_TS_DEV_DBG("%s: KC_SYSFS_CONFIG\n", __func__);
		sscanf(buf, "%c %x", &sdata.command,
					(unsigned int *) &ts_config_switching);
		KC_TS_DEV_DBG("%s: ts_config_switching is set to %d\n", __func__,
							ts_config_switching);
		break;
	case KC_SYSFS_STATUS:
		KC_TS_DEV_DBG("%s: KC_SYSFS_STATUS\n", __func__);
		sscanf(buf, "%c", &sdata.command);
		break;
	case KC_SYSFS_IRQ:
		KC_TS_DEV_DBG("%s: KC_SYSFS_IRQ\n", __func__);
		sscanf(buf, "%c %x", &sdata.command, &val);
			if (val) {
				KC_TS_DEV_DBG("%s: enable_irq\n", __func__);
				if (data->irq != -1) {
					err = data->tops->enable(data);
					if (err)
						KC_TS_DEV_DBG("%s: failed enable_irq\n",
							 __func__);
				}
			} else {
				KC_TS_DEV_DBG("%s: disable_irq\n", __func__);
				if (data->irq != -1) {
					data->tops->disable(data);
				}
			}
		break;
	case KC_SYSFS_NOTICE:
		KC_TS_DEV_DBG("%s: KC_SYSFS_NOTICE\n", __func__);
		sscanf(buf, "%c %x", &sdata.command,
					(unsigned int *) &ts_event_control);
		pr_notice("%s: ts_event_control = %x\n", __func__, ts_event_control);
		break;
	case KC_SYSFS_REFERENCE:
		KC_TS_DEV_DBG("%s: KC_SYSFS_REFERENCE\n", __func__);
		sscanf(buf, "%c %x", &sdata.command,
					(unsigned int *) &val);
		if(val == 0x10 || val == 0x11) {
			pr_notice("%s: KC_SYSFS_REFERENCE = %x\n", __func__, val);
			mutex_lock(&data->lock);
			if(data->tops->reference(data, val))
				pr_err("%s: Failed get t37_data\n",__func__);
			mutex_unlock(&data->lock);
		} else
			pr_err("%s: KC_SYSFS_REFERENCE: Invalid Parameter\n", __func__);
		break;
	default:
		break;
	}
	return count;
}

static ssize_t kc_ctrl_show(struct device *dev,
				    struct device_attribute *attr, char *buf)
{
	struct kc_ts_data *data = dev_get_drvdata(dev);
	struct mxt_object *object;
	int count = 0;
	int val;
	int last_address;
	int i;
	u16 offset;
	u8 *r_data;
	u8 *dp;

	switch (sdata.command) {
#ifdef FEATURE_TOUCH_TEST
	case KC_SYSFS_LOG_FS:
		KC_TS_DEV_DBG("%s: KC_SYSFS_LOG_FS\n", __func__);
		count += scnprintf(buf, PAGE_SIZE - count,
				   "ts_log_file_enable is [%d]\n",
				   ts_log_file_enable);
		break;
#endif
	case KC_SYSFS_POLLING:
		KC_TS_DEV_DBG("%s: KC_SYSFS_POLLING\n", __func__);
		count += scnprintf(buf, PAGE_SIZE - count, "ts_esd_recovery is "
							"[%d]\n", ts_esd_recovery);
		break;
	case KC_SYSFS_WRITE:
	case KC_SYSFS_READ:
		KC_TS_DEV_DBG("%s: KC_SYSFS_READ/WRITE\n", __func__);
		if(data->ts_sequence <= TS_SEQ_PROBE_IC_NONE){
			pr_err("%s: Touch IC does not exist\n",__func__);
			count += scnprintf(buf, PAGE_SIZE - count,
					"Touch IC does not exist\n");
			break;
		}
		object = data->vdata->object_table + (data->vdata->info.object_num - 1);
		last_address = object->start_address +
				((object->size + 1) *
				 (object->instances + 1)) - 1;
		if (sdata.start_addr > last_address) {
			dev_err(dev, "%s:Invalid start address[%04X]!\n",
						__func__, sdata.start_addr);
			return PAGE_SIZE - 1;
		}
		if ((!sdata.size) ||
		    (sdata.size > (last_address - sdata.start_addr + 1))) {
			sdata.size = last_address - sdata.start_addr + 1;
			KC_TS_DEV_DBG("%s:size is set to[%d].\n",
							__func__, sdata.size);
		}
		r_data = kcalloc(sdata.size, sizeof(u8), GFP_KERNEL);

		mutex_lock(&data->lock);
		data->tops->multi_read(data, sdata.size, sdata.start_addr, r_data);
		mutex_unlock(&data->lock);

		count += scnprintf(buf + count, PAGE_SIZE - count, "        ");
		if (count >= PAGE_SIZE) {
			kfree(r_data);
			return PAGE_SIZE - 1;
		}
		for (i = 0; i < 16; i++) {
			count += scnprintf(buf + count, PAGE_SIZE - count,
								"%2x ", i);
			if (count >= PAGE_SIZE) {
				kfree(r_data);
				return PAGE_SIZE - 1;
			}
		}
		offset = sdata.start_addr & 0xfff0;
		dp = r_data;
		for (i = 0; i < (sdata.size + (sdata.start_addr & 0xf)) ; i++) {
			if (!(i  & 0xf)) {
				count += scnprintf(buf + count,
						   PAGE_SIZE - count,
						   "\n%04x :\t",
						   i + offset);
				if (count >= PAGE_SIZE) {
					kfree(r_data);
					return PAGE_SIZE - 1;
				}
			}
			if (i < (sdata.start_addr & 0xf)) {
				count += scnprintf(buf + count,
						   PAGE_SIZE - count,
						   "   ");
				if (count >= PAGE_SIZE) {
					kfree(r_data);
					return PAGE_SIZE - 1;
				}
			} else {
				count += scnprintf(buf + count,
						   PAGE_SIZE - count,
						   "%02x ", *dp++);
				if (count >= PAGE_SIZE) {
					kfree(r_data);
					return PAGE_SIZE - 1;
				}
			}
		}
		count += scnprintf(buf + count, PAGE_SIZE - count, "\n");

		if (count >= PAGE_SIZE) {
			kfree(r_data);
			return PAGE_SIZE - 1;
		}
		kfree(r_data);
		break;	
	case KC_SYSFS_CONFIG:
		KC_TS_DEV_DBG("%s: KC_SYSFS_CONFIG\n", __func__);
		count += scnprintf(buf, PAGE_SIZE - count,
				   "config switching is [%d]\n",
				   ts_config_switching);
		break;
	case KC_SYSFS_STATUS:
		KC_TS_DEV_DBG("%s: KC_SYSFS_STATUS\n", __func__);
		count += scnprintf(buf + count, PAGE_SIZE - count,
				   "data->vdata->info.family_id is [%X]\n",
				   data->vdata->info.family_id);
		if (count >= PAGE_SIZE)
			return PAGE_SIZE - 1;
		count += scnprintf(buf + count, PAGE_SIZE - count,
				   "data->vdata->info.variant_id is [%X]\n",
				   data->vdata->info.variant_id);
		if (count >= PAGE_SIZE)
			return PAGE_SIZE - 1;
		count += scnprintf(buf + count, PAGE_SIZE - count,
				   "data->vdata->info.version is [%X]\n",
				   data->vdata->info.version);
		if (count >= PAGE_SIZE)
			return PAGE_SIZE - 1;
		count += scnprintf(buf + count, PAGE_SIZE - count,
				   "data->vdata->info.build is [%X]\n",
				   data->vdata->info.build);
		if (count >= PAGE_SIZE)
			return PAGE_SIZE - 1;
		count += scnprintf(buf + count, PAGE_SIZE - count,
				   "data->vdata->info.object_num is [%X]\n",
				   data->vdata->info.object_num);
		if (count >= PAGE_SIZE)
			return PAGE_SIZE - 1;
		count += scnprintf(buf + count, PAGE_SIZE - count,
				   "data->init_done.done is [%X]\n",
				   data->init_done.done);
		if (count >= PAGE_SIZE)
			return PAGE_SIZE - 1;
		count += scnprintf(buf + count, PAGE_SIZE - count,
				   "data->vdata->client->irq is [%d]\n",
				   data->vdata->client->irq);
		if (count >= PAGE_SIZE)
			return PAGE_SIZE - 1;
		count += scnprintf(buf + count, PAGE_SIZE - count,
				   "data->is_enable is [%d]\n",
				   data->is_enable);
		if (count >= PAGE_SIZE)
			return PAGE_SIZE - 1;
		count += scnprintf(buf + count, PAGE_SIZE - count,
				   "data->is_suspended is [%d]\n",
				   data->is_suspended);
		if (count >= PAGE_SIZE)
			return PAGE_SIZE - 1;
		count += scnprintf(buf + count, PAGE_SIZE - count,
				   "data->config_status is [%d]\n",
				   data->config_status);
		if (count >= PAGE_SIZE)
			return PAGE_SIZE - 1;
		count += scnprintf(buf + count, PAGE_SIZE - count,
				   "data->config_status_last is [%d]\n",
				   data->config_status_last);
		if (count >= PAGE_SIZE)
			return PAGE_SIZE - 1;
		count += scnprintf(buf + count, PAGE_SIZE - count,
				   "data->lock.count.counter is [%d]\n",
				   data->lock.count.counter);
		if (count >= PAGE_SIZE)
			return PAGE_SIZE - 1;
		count += scnprintf(buf + count, PAGE_SIZE - count,
				   "data->ts_sequence is [0x%02x]\n", data->ts_sequence);
		if (count >= PAGE_SIZE)
			return PAGE_SIZE - 1;
		count += scnprintf(buf + count, PAGE_SIZE - count,
				   "ts_error_status is [0x%02x]\n", ts_error_status);
		if (count >= PAGE_SIZE)
			return PAGE_SIZE - 1;
		val = gpio_get_value(data->pdata->irq_gpio);
		count += scnprintf(buf + count, PAGE_SIZE - count,
				   "CHG signal is [%d]\n", val);
		if (count >= PAGE_SIZE)
			return PAGE_SIZE - 1;
		for (i = 0; i < MXT_ERR_MAX; i++) {
			count += scnprintf(buf + count, PAGE_SIZE - count,
					   "data->vdata->err_cnt[%d] is [%d]\n",
					   i,
					   data->vdata->err_cnt[i]);
			if (count >= PAGE_SIZE)
				return PAGE_SIZE - 1;
		}
		count += scnprintf(buf + count, PAGE_SIZE - count,
				"object->type, address, size, instances, num_report, max_reportid\n");
		for (i = 0; i < data->vdata->info.object_num; i++) {
			object = data->vdata->object_table + i;
			count += scnprintf(buf + count, PAGE_SIZE - count,
				"	%d,	%d,	%d,	%d,	%d,	%d\n",
				object->type, object->start_address, object->size,
				object->instances, object->num_report_ids, object->max_reportid);
			if (count >= PAGE_SIZE)
				return PAGE_SIZE - 1;
		}
		break;
	case KC_SYSFS_REFERENCE:
		KC_TS_DEV_DBG("%s: KC_SYSFS_REFERENCE\n", __func__);
		count += scnprintf(buf, PAGE_SIZE - count,
				"Please Check kernel message\n");
		data->tops->output_reference();
		break;
	default:
		break;
	}
	return count;
}

static DEVICE_ATTR(ctrl, S_IRUGO|S_IWUSR, kc_ctrl_show, kc_ctrl_store);

static struct attribute *kc_attrs[] = {
	&dev_attr_ctrl.attr,
	NULL
};

static const struct attribute_group kc_attr_group = {
	.attrs = kc_attrs,
};

int kc_ts_probe(struct kc_ts_data *ts)
{
	struct input_dev *input_dev;
	int err = 0;
#ifdef CONFIG_KC_TOUCH_REGULATOR
	int rc = 0;
#endif

	if (!ts) {
		pr_err("%s: kc_ts data is not set.\n", __func__);
		err = -EINVAL;
		goto err_out;
	}

	if (!ts->vdata) {
		dev_err(ts->dev, "%s: kc_ts vdata is not set.\n", __func__);
		err = -EINVAL;
		goto err_free_ts;
	}

	if (!ts->pdata || !ts->tops) {
		dev_err(ts->dev, "%s: platform data is not set.\n", __func__);
		err = -EINVAL;
		goto err_free_vdata;
	}

	input_dev = input_allocate_device();
	if (!input_dev) {
		pr_err("%s: Failed to allocate memory\n",__func__);
		err = -ENOMEM;
		goto err_free_vdata;
	}

	ts->input_dev = input_dev;
	input_dev->name = KC_TS_NAME;
	input_dev->id.bustype = ts->tops->bustype;
	input_dev->dev.parent = &ts->vdata->client->dev;
	input_dev->open = kc_ts_input_open;
	input_dev->close = kc_ts_input_close;

	__set_bit(EV_ABS, input_dev->evbit);
	__set_bit(EV_KEY, input_dev->evbit);
	__set_bit(BTN_TOUCH, input_dev->keybit);
	__set_bit(EV_SYN, input_dev->evbit);
	__set_bit(KEY_HOME, input_dev->keybit);
	__set_bit(KEY_MENU, input_dev->keybit);
	__set_bit(KEY_BACK, input_dev->keybit);
	__set_bit(INPUT_PROP_DIRECT, input_dev->propbit);

	ts->tops->resolution(ts);

	input_mt_init_slots(input_dev, KC_TS_MAX_FINGER);
	input_set_abs_params(input_dev, ABS_MT_POSITION_X,  0, ts->max_x, 0, 0);
	input_set_abs_params(input_dev, ABS_MT_POSITION_Y,  0, ts->max_y, 0, 0);
	input_set_abs_params(input_dev, ABS_MT_TOUCH_MAJOR, 0, KC_TS_AREA_MAX, 0, 0);
	input_set_abs_params(input_dev, ABS_MT_PRESSURE,    0, KC_TS_FORCE_MAX, 0, 0);

	ts->is_suspended = true;

	mutex_init(&ts->lock);
	init_completion(&ts->init_done);

	input_set_drvdata(input_dev, ts);
	i2c_set_clientdata(ts->vdata->client, ts);

#ifdef CONFIG_KC_TOUCH_REGULATOR
	ts->ts_sequence = TS_SEQ_PROBE_REGULATOR;
	ts->reg_touch = regulator_get(&ts->vdata->client->dev, "vdd_atmel");
	if(IS_ERR(ts->reg_touch)){
		pr_err("%s regulator is not get\n",__func__);
	}
	if(ts->reg_touch)
		rc = regulator_set_optimum_mode(ts->reg_touch, 50000);
	if(rc < 0){
		pr_err("%s regulator set error\n",__func__);
#ifdef	FEATURE_FACTORY_TEST
		goto err_dev_access;
#else
		goto err_free_mutex;
#endif
	} else
		KC_TS_DEV_DBG("%s regulator set 0x%02x\n",__func__,rc);
	usleep_range(1000, 1000);
#endif

	ts->ts_sequence = TS_SEQ_PROBE_SETTING;
	if (ts->pdata->init_hw)
		err = ts->pdata->init_hw();

	if(err) {
		pr_err("%s: Failed to initialize hardware\n",__func__);
#ifdef	FEATURE_FACTORY_TEST
		goto err_dev_access;
#else
		goto err_free_mutex;
#endif
	}

	ts->ts_sequence = TS_SEQ_PROBE_IC_NONE;
	err = ts->tops->reset(ts);
	if (err) {
		pr_err("%s: Failed to reset & Prohibit the Sysfs R/W\n",__func__);
#ifdef	FEATURE_FACTORY_TEST
		goto err_dev_access;
#else
		goto err_free_mutex;
#endif
	}

	ts->ts_sequence = TS_SEQ_PROBE_INITIALIZATION;
	err = ts->tops->initialize(ts);
	if (err) {
		pr_err("%s: Failed to initialize.\n",__func__);
		if(ts->tops->mode_check){
			if(ts->tops->mode_check(ts)) {
				pr_notice("%s: AppMode or Not MXT_APP_CRC_FAIL\n", __func__);
			} else {
				ts->ts_sequence = TS_SEQ_PROBE_BOOTLOADER_MODE;
				pr_notice("%s: BootLoader & MXT_APP_CRC_FAIL\n", __func__);
				goto bootloader_mode;
			}
			goto err_free_mutex;
		}
	}

	ts->is_suspended = false;
	ts->ts_sequence = TS_SEQ_PROBE_INTERRUPT_REGISTER;

	err = request_threaded_irq(ts->irq, NULL, kc_ts_interrupt,
			ts->pdata->irqflags, ts->vdata->client->dev.driver->name, ts);
	if (err) {
		dev_err(ts->dev, "Failed to register interrupt\n");
#ifdef CONFIG_TOUCHSCREEN_ATMEL_MXT_KC
		goto err_free_object;
#else
		goto err_free_mutex;
#endif
	}

	disable_irq(ts->irq);
	complete_all(&ts->init_done);
	ts->ts_sequence = TS_SEQ_PROBE_CREATE_QUEUE;

	ts->wq = alloc_workqueue("kc_ts_wq", WQ_MEM_RECLAIM, 1);
	ts->calib_wq = alloc_workqueue("kc_ts_calib_wq", WQ_MEM_RECLAIM, 1);
	if ((!ts->wq) || (!ts->calib_wq)) {
		pr_err("%s: Fail to allocate workqueue!\n", __func__);
		err = -ENOMEM;
		goto err_free_irq;
	}

	ts->ts_sequence = TS_SEQ_PROBE_START_QUEUE;
	if ((ts->wq) && (ts->calib_wq)) {
		INIT_DELAYED_WORK(&ts->esdwork, kc_ts_esd_work);
		INIT_DELAYED_WORK(&ts->calib_work, kc_ts_golden_cal);
		queue_delayed_work(ts->wq, &ts->esdwork,
				   msecs_to_jiffies(10000));
	}

	err = input_register_device(input_dev);
	if (err) {
		pr_err("%s: input_register_device\n",__func__);
		goto err_free_wq;
	}

	ts->ts_sequence = TS_SEQ_PROBE_CREATE_SYSFS;
	/* Create sysfs */
	err = sysfs_create_group(&ts->vdata->client->dev.kobj, &kc_attr_group);
	if (err)
		goto err_unregister_device;

	/* Create cdev file ts_ctrl */
	ts_ctrl_init(ts, &kc_ts_fops);
	ts->ts_sequence = TS_SEQ_PROBE_CREATE_SUSPEND;

#if defined(CONFIG_KC_TOUCH_FB)
	ts->fb_notif.notifier_call = fb_notifier_callback;
	err = fb_register_client(&ts->fb_notif);
	if (err)
		pr_err("%s Unable to register fb_notifier: %d\n", __func__, err);
#elif defined(CONFIG_KC_TOUCH_EARLY_SUSPEND)
	ts->early_suspend.level = EARLY_SUSPEND_LEVEL_BLANK_SCREEN + 1;
	ts->early_suspend.suspend = kc_ts_early_suspend;
	ts->early_suspend.resume = kc_ts_late_resume;
	register_early_suspend(&ts->early_suspend);
#endif
	ts->ts_sequence = TS_SEQ_PROBE_END;
	return 0;

err_unregister_device:
	input_unregister_device(input_dev);
err_free_wq:
	if (ts->wq) {
		cancel_delayed_work_sync(&ts->esdwork);
		flush_workqueue(ts->wq);
	}
	destroy_workqueue(ts->wq);
err_free_irq:
	free_irq(ts->irq, ts);
#ifdef CONFIG_TOUCHSCREEN_ATMEL_MXT_KC
err_free_object:
	kfree(ts->vdata->object_table);
#endif /* CONFIG_TOUCHSCREEN_ATMEL_MXT_KC */
err_free_mutex:
	mutex_destroy(&ts->lock);
	input_free_device(input_dev);
err_free_vdata:
	kfree(ts->vdata);
err_free_ts:
	kfree(ts);
err_out:
	return err;

#ifdef FEATURE_FACTORY_TEST
err_dev_access:
	ts->vdata->client->irq = -1;
bootloader_mode:
	ts->irq = -1;
	complete_all(&ts->init_done);
	err = input_register_device(input_dev);
	if (err)
		goto err_free_mutex;
	err = sysfs_create_group(&ts->vdata->client->dev.kobj, &kc_attr_group);
	if (err)
		goto err_unregister_device;
	ts_ctrl_init(ts, &kc_ts_fops);
	return err;
#endif
}
EXPORT_SYMBOL(kc_ts_probe);

void kc_ts_remove(struct kc_ts_data *ts)
{
	int i;
	KC_TS_DEV_DBG("%s is called.\n", __func__);
	sysfs_remove_group(&ts->vdata->client->dev.kobj, &kc_attr_group);
	if (ts->irq != -1)
		free_irq(ts->irq, ts);
	input_unregister_device(ts->input_dev);
	input_free_device(ts->input_dev);
#if defined(CONFIG_KC_TOUCH_FB)
	if (fb_unregister_client(&ts->fb_notif))
		pr_err("%s Error occurred while unregistering fb_notifier.\n",__func__);
#elif defined(CONFIG_KC_TOUCH_EARLY_SUSPEND)
	unregister_early_suspend(&ts->early_suspend);
#endif
	ts_ctrl_exit(ts);

	for (i = 0; i < TS_CONFIG_MAX; i++) {
		if (ts->config_nv[i].data)
			kfree(ts->config_nv[i].data);
	}

	kfree(ts->vdata);
	kfree(ts);

	KC_TS_DEV_DBG("Core[%d]: %s is completed.\n",
					smp_processor_id(), __func__);
	return;

}
EXPORT_SYMBOL(kc_ts_remove);

void kc_ts_shutdown(struct kc_ts_data *ts)
{

	if(ts->wq){
		cancel_delayed_work_sync(&ts->esdwork);
		flush_workqueue(ts->wq);
	}

	mutex_lock(&ts->lock);
	if (ts->pdata->shutdown)
		ts->pdata->shutdown();
	mutex_unlock(&ts->lock);

	return;

}
EXPORT_SYMBOL(kc_ts_shutdown);

MODULE_AUTHOR("KYOCERA Corporation");
MODULE_DESCRIPTION("kc touchscreen driver");
MODULE_LICENSE("GPL");

