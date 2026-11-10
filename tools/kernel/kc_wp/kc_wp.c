/*
 * kc_wp - eMMC 写保护清除/诊断模块（调试用，随 TWRP 一起加载）
 *
 * /sys/kernel/kc_wp/run 接受的命令：
 *   autofix <分区名>   对整个分区做双单位(字节/扇区) CMD29 扫描并复查
 *                      （insmod 后 4s 的自动清除和手动排查走的都是它）
 *   auto    <分区名>   先用 CMD31 探出地址单位，再清一次（单次，调试用）
 *   info               打印 EXT_CSD 的 USER_WP / WR_REL_SET / SECURE_WP
 *   29 <arg>  / 31 <arg>   原始命令，参数按十六进制(0x...)或十进制
 *   13                 读 CMD13 卡状态
 *
 * 拿设备的两条硬规矩（fs/block_dev.c 里写死的，踩过两次）：
 *   - lookup_bdev() 只 bd_acquire()，不打开设备，返回的 bdev 上 bd_part /
 *     bd_contains 都是 NULL；要它们必须 blkdev_get_by_path()。
 *   - mmcblk0pN 的分区 gendisk 没有 driverfs_dev（add_partition 不设），
 *     必须沿 bd_contains 上溯到整盘 mmcblk0 才拿得到 card->dev。
 */
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/kobject.h>
#include <linux/sysfs.h>
#include <linux/blkdev.h>
#include <linux/genhd.h>
#include <linux/slab.h>
#include <linux/scatterlist.h>
#include <linux/workqueue.h>
#include <linux/string.h>
#include <linux/mmc/card.h>
#include <linux/mmc/host.h>
#include <linux/mmc/core.h>

#define TAG "kc_wp: "

static struct kobject *kcw_kobj;

/* ---------- 基础 ---------- */

/*
 * 从路径拿到 mmc_card。
 *
 * 两个坑都在 fs/block_dev.c 里：
 *  1) lookup_bdev() 只做 bd_acquire()，不打开设备，所以返回的 bdev 上
 *     bd_part / bd_contains 全是 NULL；要拿到它们必须 blkdev_get_by_path()。
 *  2) mmcblk0pN 是分区盘，它的 gendisk 由 add_partition() 建立，
 *     block/partition-generic.c 不设 driverfs_dev（alloc_disk_node 清成
 *     NULL）；只有整盘 mmcblk0 才 driverfs_dev = &card->dev。
 *     所以要沿 bd_contains 上溯一层再 container_of。
 */
static struct mmc_card *kcw_card_of(const char *path)
{
	struct block_device *bdev, *whole;
	struct gendisk *disk;
	struct mmc_card *card = NULL;

	bdev = blkdev_get_by_path(path, FMODE_READ, NULL);
	if (IS_ERR(bdev)) {
		pr_err(TAG "blkdev_get_by_path(%s) -> %ld\n", path,
		       PTR_ERR(bdev));
		return NULL;
	}

	whole = (bdev->bd_contains && bdev->bd_contains != bdev)
		? bdev->bd_contains : bdev;
	disk = whole->bd_disk;
	if (!disk || !disk->driverfs_dev) {
		pr_err(TAG "%s: no gendisk/driverfs_dev\n", path);
		goto out;
	}

	card = container_of(disk->driverfs_dev, struct mmc_card, dev);
	if (!card->host) {
		pr_err(TAG "%s: container_of 结果无 host，放弃\n", path);
		card = NULL;
	}
out:
	blkdev_put(bdev, FMODE_READ);
	return card;
}

/*
 * 取分区的起始扇区/长度。同样必须先真打开：只有 blkdev_get_by_path()
 * 才会把 bd_part 挂上（lookup_bdev 拿到的 bdev->bd_part 是 NULL）。
 */
static int kcw_part_info(const char *path, u64 *start_sect, u64 *nr_sects)
{
	struct block_device *bdev;
	int ret = -ENODEV;

	bdev = blkdev_get_by_path(path, FMODE_READ, NULL);
	if (IS_ERR(bdev)) {
		pr_err(TAG "part_info(%s): blkdev_get -> %ld\n", path,
		       PTR_ERR(bdev));
		return PTR_ERR(bdev);
	}
	if (bdev->bd_part) {
		*start_sect = (u64)bdev->bd_part->start_sect;
		*nr_sects = (u64)bdev->bd_part->nr_sects;
		ret = 0;
	}
	blkdev_put(bdev, FMODE_READ);
	return ret;
}

/*
 * 把 "mmcblk0p12" 补成 "/dev/block/mmcblk0p12"。
 * 别指望调用方给全路径：init.rc 和 shell 里传的都是裸名字，而
 * kern_path("mmcblk0p12") 是相对路径，必然 -ENOENT(-2)。
 */
static void kcw_dev_path(const char *name, char *out, size_t n)
{
	if (name[0] == '/')
		snprintf(out, n, "%s", name);
	else
		snprintf(out, n, "/dev/block/%s", name);
}

static int kcw_cmd_q(struct mmc_card *card, u32 opcode, u32 arg, u32 *r1)
{
	struct mmc_command cmd;

	memset(&cmd, 0, sizeof(cmd));
	cmd.opcode = opcode;
	cmd.arg = arg;
	cmd.flags = MMC_RSP_R1B | MMC_CMD_AC;

	mmc_claim_host(card->host);
	mmc_wait_for_cmd(card->host, &cmd, 3);
	mmc_release_host(card->host);

	if (r1)
		*r1 = cmd.resp[0];
	return cmd.error;
}

static int kcw_cmd(struct mmc_card *card, u32 opcode, u32 arg)
{
	struct mmc_command cmd, dummy;

	memset(&cmd, 0, sizeof(cmd));
	cmd.opcode = opcode;
	cmd.arg = arg;
	cmd.flags = MMC_RSP_R1B | MMC_CMD_AC;

	mmc_claim_host(card->host);
	mmc_wait_for_cmd(card->host, &cmd, 3);
	mmc_release_host(card->host);

	pr_err(TAG "CMD%u arg=0x%08x ret=%d R1=0x%08x%s%s%s\n",
	       opcode, arg, cmd.error, cmd.resp[0],
	       (cmd.resp[0] & (1u << 31)) ? " OUT_OF_RANGE" : "",
	       (cmd.resp[0] & (1u << 26)) ? " WP_VIOLATION" : "",
	       (cmd.resp[0] & (1u << 19)) ? " ERROR" : "");
	(void)dummy;
	return cmd.error;
}

static int kcw_read_extcsd(struct mmc_card *card, u8 *buf)
{
	struct mmc_request mrq;
	struct mmc_command cmd;
	struct mmc_data data;
	struct scatterlist sg;

	memset(buf, 0, 512);
	memset(&mrq, 0, sizeof(mrq));
	memset(&cmd, 0, sizeof(cmd));
	memset(&data, 0, sizeof(data));

	cmd.opcode = 8;
	cmd.arg = 0;
	cmd.flags = MMC_RSP_R1 | MMC_CMD_ADTC;

	data.blksz = 512;
	data.blocks = 1;
	data.flags = MMC_DATA_READ;
	data.sg = &sg;
	data.sg_len = 1;
	sg_init_one(&sg, buf, 512);

	mrq.cmd = &cmd;
	mrq.data = &data;

	mmc_claim_host(card->host);
	mmc_set_data_timeout(&data, card);
	mmc_wait_for_req(card->host, &mrq);
	mmc_release_host(card->host);

	return cmd.error ? cmd.error : data.error;
}

static int kcw_cmd31(struct mmc_card *card, u32 arg, u64 *val)
{
	struct mmc_request mrq;
	struct mmc_command cmd;
	struct mmc_data data;
	struct scatterlist sg;
	void *buf;
	int ret;

	buf = kmalloc(8, GFP_KERNEL);
	if (!buf)
		return -ENOMEM;
	memset(buf, 0, 8);

	memset(&mrq, 0, sizeof(mrq));
	memset(&cmd, 0, sizeof(cmd));
	memset(&data, 0, sizeof(data));

	cmd.opcode = 31;
	cmd.arg = arg;
	cmd.flags = MMC_RSP_R1 | MMC_CMD_ADTC;

	data.blksz = 8;
	data.blocks = 1;
	data.flags = MMC_DATA_READ;
	data.sg = &sg;
	data.sg_len = 1;
	sg_init_one(&sg, buf, 8);

	mrq.cmd = &cmd;
	mrq.data = &data;

	mmc_claim_host(card->host);
	mmc_set_data_timeout(&data, card);
	mmc_wait_for_req(card->host, &mrq);
	mmc_release_host(card->host);

	*val = *(u64 *)buf;
	kfree(buf);
	ret = cmd.error ? cmd.error : data.error;
	pr_err(TAG "CMD31 arg=0x%08x ret=%d R1=0x%08x data=%016llx\n",
	       arg, ret, cmd.resp[0], *val);
	return ret;
}

/* ---------- EXT_CSD ---------- */

static void kcw_dump_extcsd(struct mmc_card *card)
{
	u8 *buf;
	int i, err;

	buf = kmalloc(512, GFP_KERNEL);
	if (!buf)
		return;
	err = kcw_read_extcsd(card, buf);
	if (err) {
		pr_err(TAG "读 EXT_CSD 失败 %d\n", err);
		kfree(buf);
		return;
	}
	pr_err(TAG "EXT_CSD rev=%d\n", buf[192]);
	for (i = 160; i < 176; i++)
		pr_err(TAG "  ext_csd[%d] = 0x%02x\n", i, buf[i]);
	pr_err(TAG "  WR_REL_SET(167)=0x%02x USER_WP(171)=0x%02x "
	       "SECURE_WP_INFO(224..227)=%02x %02x %02x %02x\n",
	       buf[167], buf[171], buf[224], buf[225], buf[226], buf[227]);
	pr_err(TAG "  HC_WP_GRP_SIZE(221)=%u HC_ERASE_GRP_SIZE(224)=%u -> "
	       "wp_grp=%u sectors\n",
	       (buf[221] & 0x1f) + 1, (buf[224] & 0x1f) + 1,
	       ((buf[221] & 0x1f) + 1) * ((buf[224] & 0x1f) + 1));
	kfree(buf);
}

static u32 kcw_grp_sectors(struct mmc_card *card)
{
	u8 *buf;
	u32 g = 0;

	buf = kmalloc(512, GFP_KERNEL);
	if (!buf)
		return 1024;
	if (!kcw_read_extcsd(card, buf)) {
		g = ((buf[221] & 0x1f) + 1) * ((buf[224] & 0x1f) + 1);
		/* 合理范围：16KB ~ 8MB */
		if (g < 32 || g > (16 << 10))
			g = 0;
	}
	kfree(buf);
	return g ? g : 1024;	/* 兜底 512KB */
}

/* ---------- 清除 ---------- */

static int kcw_autofix(const char *name)
{
	u64 start_sect = 0, nr_sects = 0;
	u32 grp, step, loops, i, err = 0, errs_a = 0, errs_b = 0, r1 = 0;
	u64 a0, b0, a1, b1;
	struct mmc_card *card;
	char path[64];

	kcw_dev_path(name, path, sizeof(path));
	card = kcw_card_of(path);
	if (!card) {
		pr_err(TAG "autofix %s: 设备还没就绪\n", path);
		return -ENODEV;
	}
	pr_err(TAG "autofix %s: 拿到卡 host=%s rca=0x%04x\n",
	       path, mmc_hostname(card->host), card->rca);
	if (kcw_part_info(path, &start_sect, &nr_sects)) {
		pr_err(TAG "autofix %s: 拿不到分区信息\n", path);
		return -ENODEV;
	}
	if (!nr_sects) {
		pr_err(TAG "autofix %s: 分区长度为 0\n", path);
		return -ENODATA;
	}

	grp = kcw_grp_sectors(card);

	/*
	 * 步长不猜组大小：WP 组至少 512KB(1024 扇区)，这里按 256KB(512 扇区)
	 * 走，每个组必然被踩到一次。猜大了会漏组，猜小了只是多发几条命令。
	 */
	step = 512;
	{
		u32 n32 = (nr_sects > 0xffffffffULL) ? 0xffffffffU
						    : (u32)nr_sects;
		loops = (n32 + step - 1) / step;
	}

	pr_err(TAG "===== autofix %s start_sect=%llu(0x%llx) nr_sects=%llu "
	       "wp_grp~%u sectors step=%u loops=%u\n",
	       path, start_sect, start_sect, nr_sects, grp, step, loops);

	/* 先把两种单位下分区起点的保护类型读出来，作为基线 */
	kcw_cmd31(card, (u32)start_sect, &a0);		/* 假设参数=扇区 */
	kcw_cmd31(card, (u32)(start_sect << 9), &b0);	/* 假设参数=字节 */
	pr_err(TAG "基线: 扇区口径=%016llx 字节口径=%016llx\n", a0, b0);

	/* A：参数按扇区 */
	for (i = 0; i < loops; i++) {
		err = kcw_cmd_q(card, 29, (u32)(start_sect + (u64)i * step), &r1);
		if (i == 0)
			pr_err(TAG "  A[0] CMD29 arg=0x%08x ret=%d R1=0x%08x\n",
			       (u32)start_sect, err, r1);
		if (err)
			errs_a++;
	}
	/* B：参数按字节 */
	for (i = 0; i < loops; i++) {
		err = kcw_cmd_q(card, 29,
				(u32)((start_sect + (u64)i * step) << 9), &r1);
		if (i == 0)
			pr_err(TAG "  B[0] CMD29 arg=0x%08x ret=%d R1=0x%08x\n",
			       (u32)(start_sect << 9), err, r1);
		if (err)
			errs_b++;
	}

	kcw_cmd31(card, (u32)start_sect, &a1);
	kcw_cmd31(card, (u32)(start_sect << 9), &b1);

	pr_err(TAG "autofix %s: 扇区口径 失败%u/%u  字节口径 失败%u/%u\n",
	       path, errs_a, loops, errs_b, loops);
	pr_err(TAG "autofix %s: 复查 扇区=%016llx 字节=%016llx -> %s\n",
	       path, a1, b1,
	       (a1 || b1) ? "仍有保护位(需看哪套口径)" : "两套口径都读到干净");
	{
		u32 g0 = (u32)((a0 >> 62) & 3), g1 = (u32)((a1 >> 62) & 3);
		pr_err(TAG "autofix %s: 起始 WP 组类型 %u -> %u  %s\n",
		       path, g0, g1,
		       (g0 && !g1) ? "(已清除)" :
		       (!g1 ? "(本来就干净)" : "(仍被保护)"));
	}
	pr_err(TAG "===== autofix %s done\n", path);
	return 0;
}

static void kcw_auto(const char *name)
{
	u64 start_sect = 0, nr_sects = 0, v_byte = 0, v_sect = 0, after = 0;
	u32 arg;
	struct mmc_card *card;
	char path[64];

	kcw_dev_path(name, path, sizeof(path));
	card = kcw_card_of(path);
	if (!card)
		return;

	kcw_part_info(path, &start_sect, &nr_sects);
	pr_err(TAG "== %s start_sect=%llu(0x%llx) nr_sects=%llu host=%s\n",
	       name, start_sect, start_sect, nr_sects, mmc_hostname(card->host));

	kcw_cmd31(card, (u32)(start_sect << 9), &v_byte);
	kcw_cmd31(card, (u32)start_sect, &v_sect);

	if (v_byte)
		arg = (u32)(start_sect << 9);
	else if (v_sect)
		arg = (u32)start_sect;
	else {
		pr_err(TAG "== 两种口径读回都是 0，该分区不在已保护的组里\n");
		return;
	}

	pr_err(TAG "== 用 0x%08x 发 CMD29\n", arg);
	kcw_cmd(card, 29, arg);
	kcw_cmd31(card, arg, &after);
	pr_err(TAG "== 结果: %s\n", after ? "仍被保护 (FAIL)" : "已解除 (OK)");
}


/* ---------- 开机自动清除（不依赖 init.rc 的 exec） ---------- */

/*
 * aboot 每次上电按 WP group 把 boot / recovery / system 三片区域一起上锁，
 * 写受保护区不报错、数据直接丢。三片都要清：只清前两个的话，刷 system.img
 * 会「报成功、回读没变」，重启还是原厂系统。
 *   mmcblk0p11 = boot, mmcblk0p12 = recovery, mmcblk0p19 = system
 */
static char *kcw_parts = "mmcblk0p12 mmcblk0p11 mmcblk0p19";
module_param_named(parts, kcw_parts, charp, 0644);
MODULE_PARM_DESC(parts, "开机要清写保护的分区，空格分隔");

static int kcw_boot = 1;
module_param_named(autofix, kcw_boot, int, 0644);
MODULE_PARM_DESC(autofix, "1=insmod 后自动清除（默认），0=关闭");

static int kcw_delay_ms = 4000;
module_param_named(delay, kcw_delay_ms, int, 0644);
MODULE_PARM_DESC(delay, "首次尝试前等多少毫秒，默认 4000");

static int kcw_retry = 15;
module_param_named(retry, kcw_retry, int, 0644);
MODULE_PARM_DESC(retry, "设备没就绪时重试次数，每次间隔 500ms");

static void kcw_boot_work(struct work_struct *w);
static DECLARE_DELAYED_WORK(kcw_dwork, kcw_boot_work);
static int kcw_tries;

static void kcw_boot_work(struct work_struct *w)
{
	char list[96], *p, *tok;
	int n = 0, failed = 0;

	strlcpy(list, kcw_parts, sizeof(list));
	p = list;
	while ((tok = strsep(&p, " ,\t")) != NULL) {
		if (!*tok)
			continue;
		n++;
		if (kcw_autofix(tok) < 0)
			failed++;
	}

	if (!failed) {
		pr_err(TAG "boot: 自动清除完成（%d 个分区）\n", n);
		return;
	}
	if (++kcw_tries <= kcw_retry) {
		pr_err(TAG "boot: %d/%d 个分区还没就绪，500ms 后第 %d 次重试\n",
		       failed, n, kcw_tries + 1);
		schedule_delayed_work(&kcw_dwork, msecs_to_jiffies(500));
		return;
	}
	pr_err(TAG "boot: 重试 %d 次仍失败，放弃（可用 echo autofix ... 手动补）\n",
	       kcw_retry);
}

/* ---------- sysfs ---------- */

static ssize_t run_store(struct kobject *kobj, struct kobj_attribute *attr,
			 const char *buf, size_t count)
{
	char op[12], name[32];
	unsigned long arg = 0;
	struct mmc_card *card;

	op[0] = 0;
	name[0] = 0;
	if (sscanf(buf, "%11s %lx", op, &arg) < 1)
		return count;

	card = kcw_card_of("/dev/block/mmcblk0p12");
	if (!card)
		card = kcw_card_of("/dev/block/mmcblk0");
	if (!card) {
		pr_err(TAG "找不到 mmc_card\n");
		return count;
	}

	if (!strcmp(op, "autofix")) {
		if (sscanf(buf, "%*s %31s", name) == 1)
			kcw_autofix(name);
		else
			kcw_autofix("mmcblk0p12");
	} else if (!strcmp(op, "auto")) {
		if (sscanf(buf, "%*s %31s", name) == 1)
			kcw_auto(name);
		else
			kcw_auto("mmcblk0p12");
	} else if (!strcmp(op, "info")) {
		pr_err(TAG "info: host=%s\n", mmc_hostname(card->host));
		kcw_dump_extcsd(card);
	} else if (!strcmp(op, "29")) {
		kcw_cmd(card, 29, (u32)arg);
	} else if (!strcmp(op, "28")) {
		kcw_cmd(card, 28, (u32)arg);
	} else if (!strcmp(op, "31")) {
		u64 v;
		kcw_cmd31(card, (u32)arg, &v);
	} else if (!strcmp(op, "13")) {
		kcw_cmd(card, 13, (u32)card->rca << 16);
	} else if (!strcmp(op, "8")) {
		kcw_dump_extcsd(card);
	} else {
		pr_err(TAG "未知命令 %s\n", op);
	}
	return count;
}

static struct kobj_attribute run_attr = __ATTR(run, 0644, NULL, run_store);

static int __init kcw_init(void)
{
	int ret;

	kcw_kobj = kobject_create_and_add("kc_wp", kernel_kobj);
	if (!kcw_kobj)
		return -ENOMEM;
	ret = sysfs_create_file(kcw_kobj, &run_attr.attr);
	if (ret) {
		kobject_put(kcw_kobj);
		return ret;
	}
	if (kcw_boot) {
		pr_err(TAG "loaded, %d ms 后自动清除: %s\n",
		       kcw_delay_ms, kcw_parts);
		schedule_delayed_work(&kcw_dwork,
				      msecs_to_jiffies(kcw_delay_ms));
	} else {
		pr_err(TAG "loaded (autofix=0，不自动清除)\n");
	}
	return 0;
}

static void __exit kcw_exit(void)
{
	cancel_delayed_work_sync(&kcw_dwork);
	sysfs_remove_file(kcw_kobj, &run_attr.attr);
	kobject_put(kcw_kobj);
}

module_init(kcw_init);
module_exit(kcw_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("eMMC write-protect helper");
