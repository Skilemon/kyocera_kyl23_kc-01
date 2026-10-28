# Kyocera KC-01 / miraie KYL23 device tree (MSM8926)

Platform bring-up tree for porting TWRP / LineageOS 14.1 (Android 7.1)
to the Kyocera KC-01 (UQ mobile) and Kyocera miraie KYL23 (au).

The two devices share an identical mainboard (verified by kernel source
diff: 27,205 files, only 29 differ - touch calibration, battery data,
one hardware key, sensor tuning).

## Status: bring-up

- [x] Partition layout dumped from device
- [x] Kernel sources obtained (KC-01 102.0.1e20, matches running firmware)
- [ ] TWRP boot
- [ ] LineageOS 14.1 boot

## Partition layout (from live device, KC-01 firmware)

| Partition | Block | Size | FS |
|---|---|---|---|
| modem | mmcblk0p1 | 64 MiB | vfat (mounted /firmware) |
| sbl1/sbl1bak | p2/p3 | 1 MiB | - |
| sdi/sdibk | p4/p15 | 1 MiB | - |
| aboot/abootbak/abootbk | p5/p6/p16 | 2 MiB | - |
| rpm/rpmbak/rpmbk | p7/p8/p17 | 1 MiB | - |
| boot | p9 | 16 MiB | bootimg |
| tz/tzbak/tzbk | p10/p11/p18 | 1 MiB | - |
| recovery | p12 | 16 MiB | bootimg |
| fota/fotabk | p13/p14 | 16 MiB | - |
| system | p19 | 1404 MiB | ext4 |
| userdata | p20 | 5205 MiB | ext4 |
| cache | p21 | 458 MiB | ext4 |
| log/logwork | p22/p23 | 20 MiB | - |
| bootwork/rom | p24/p25 | 4 MiB | - |
| misc | p26 | 6 MiB | - |
| DDR | p27 | 1 MiB | - |
| fsg | p28 | 8 MiB | - |
| fsc | p29 | 1 MiB | - |
| ssd/pad | p30/p31 | 1 MiB | - |
| carrier | p32 | 8 MiB | ext4 |
| fotamng | p33 | 4 MiB | - |
| reserve1 | p34 | 100 MiB | - |
| persist | p35 | 8 MiB | ext4 |
| dnand | p36 | 8 MiB | - |
| sysprop | p37 | 8 MiB | ext4 |
| modemst1/modemst2 | p38/p39 | 1.5 MiB | - |
| bfss1/bfss2 | p40/p41 | 4/8 MiB | - |
| sysprop2 | p42 | 8 MiB | ext4 (pstore) |
| reserve2 | p43 | 6 MiB | - |

## Kernel

Base: LineageOS android_kernel_motorola_msm8226 (cm-14.1, Nougat-ready
CAF 3.4) + Kyocera device drivers grafted from kernel_KC-01_102.0.1e20:

- drivers/input/touchscreen/atmel_mxt_kc.c (touch)
- drivers/sensors/sfh7776.c, yas_mag_kernel_driver.c (sensors)
- arch/arm/mach-msm/bms-batterydata-oem*.c (battery)
- arch/arm/boot/dts/msm8226-720p-mtp.dtsi (board/pinctrl/panel)
- drivers/usb/gadget/f_kc_serial.c (Kyocera serial)

## Credits

- LineageOS / CyanogenMod msm8226 maintainers (thea/falcon/g2m trees)
