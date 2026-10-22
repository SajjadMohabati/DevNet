# DevNet برای لینوکس

نسخه‌ی بومی لینوکسِ [DevNet](https://github.com/SajjadMohabati/DevNet) با GTK4 و libadwaita.
همان چهار بخش نسخه‌ی macOS را دارد:

- **Routes** — شبکه‌ها، هاست‌ها، دامنه‌ها یا محدوده‌های IP یک کشور را از VPN دور می‌زند و
  مسیرها را بعد از تغییر Wi-Fi یا VPN خودکار اصلاح می‌کند.
- **Projects** — سرویس‌های محلی و کانتینرهای Docker/Podman را پیدا می‌کند و باز کردن یا
  متوقف کردن آن‌ها را ممکن می‌کند.
- **DNS** — پریست‌های Shecan، Shecan Pro، Electro، Begzar، 403، Radar Game، Google و
  Cloudflare را روی همه‌ی لینک‌های فعال، از جمله لینک VPN، اعمال می‌کند.
- **Speed** — تست سرعت Cloudflare با نمودار زنده و تاریخچه، به‌همراه پینگ زنده.

## پیش‌نیازها

- دبیان ۱۲+، اوبونتو ۲۲.۱۰+، فدورا ۳۷+ یا RHEL 9 همراه با EPEL
- Python 3.9+ و PyGObject
- بسته‌های `iproute2` و `iputils`
- polkit برای اجرای helper
- در GNOME برای آیکن سینی به افزونه‌ی AppIndicator نیاز است؛ پنجره، پنل و میان‌بر بدون آن
  هم کار می‌کنند.

```bash
# Debian / Ubuntu
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 \
  iproute2 iputils-ping pkexec desktop-file-utils hicolor-icon-theme

# Fedora / Red Hat
sudo dnf install python3 python3-gobject python3-cairo gtk4 libadwaita iproute iputils polkit \
  desktop-file-utils hicolor-icon-theme
```

## نصب

```bash
# بسته‌ی دبیان
sudo apt install ./devnet_1.2.0_all.deb

# بسته‌ی RPM
sudo dnf install ./devnet-1.2.0-1.*.noarch.rpm

# از همین مخزن
sudo ./linux/install.sh
```

برای اجرای مستقیم بدون نصب:

```bash
./linux/run.sh
```

پس از باز کردن برنامه، یک‌بار **Enable Passwordless Mode** را در نوار کناری بزنید تا
تغییر مسیرها و DNS بدون پرسیدن رمز انجام شود. این گزینه فقط اجازه‌ی اجرای
`/usr/libexec/devnet/devnet-helper` را برای کاربر فعلی می‌دهد و دسترسی root عمومی نمی‌دهد.

## دستورها

```bash
devnet              # پنجره‌ی اصلی
devnet --panel      # باز/بستن پنل کوچک
devnet --background # شروع مخفی در سینی
devnet --version
```

میان‌بر پیش‌فرض `Ctrl+Shift+I` است و از بخش تنظیمات نوار کناری قابل تغییر است. این میان‌بر
روی GNOME با `gsettings` ثبت می‌شود؛ در دسکتاپ‌های دیگر از سینی یا `devnet --panel` استفاده
کنید.

## امنیت و نحوه‌ی کار

رابط گرافیکی هرگز `ip` یا ابزارهای DNS را با root اجرا نمی‌کند. یک درخواست JSON کوچک
می‌سازد و helper را با `pkexec` صدا می‌زند. helper فقط چند عملیات ثابت را قبول می‌کند،
ورودی‌ها را اعتبارسنجی می‌کند، فایل درخواست را از نظر مالکیت و اندازه بررسی می‌کند و
دستورها را با `flock` سریالی می‌کند.

- مسیرها با یک batch از `ip route replace/delete` اعمال می‌شوند.
- DNS با systemd-resolved، NetworkManager یا `/etc/resolv.conf` تنظیم می‌شود و نسخه‌ی
  پشتیبان در `/var/lib/devnet` نگه داشته می‌شود.
- حالت **Automatic** نسخه‌ی قبلی DNS را برمی‌گرداند.
- پکیج‌ها قانون polkit را در `/etc/polkit-1/rules.d/50-devnet.rules` قرار می‌دهند و هنگام
  حذف پاک می‌کنند.

## ساخت بسته‌ها

```bash
./linux/package/deb/build.sh    # build/deb/devnet_1.2.0_all.deb
./linux/package/rpm/build.sh    # build/rpm/devnet-1.2.0-1.*.noarch.rpm
```

## تست‌ها

```bash
PYTHONPATH=linux/src python3 -m unittest discover -s linux/tests -v
python3 -m compileall -q linux/src
desktop-file-validate linux/data/org.devnet.App.desktop
appstreamcli validate --no-net linux/data/org.devnet.App.metainfo.xml
```

## حذف

```bash
sudo apt remove devnet        # یا: sudo apt purge devnet
sudo dnf remove devnet
sudo ./linux/install.sh --uninstall
```

تنظیمات و تاریخچه در `~/.config/devnet` و `~/.local/share/devnet` باقی می‌مانند. برای پاک
کردن کامل، این دو پوشه و در RPM پوشه‌ی `/var/lib/devnet` را هم حذف کنید.

راهنمای کامل انگلیسی: [README.md](README.md)
