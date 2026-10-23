<div align="center">

<img src="docs/icon.png" width="128" alt="أيقونة DevNet — تقسيم نفق VPN على ماك ولينكس">

# DevNet — تقسيم نفق VPN وتجاوزه على macOS ولينكس

**مرّر الشبكات والنطاقات ودولاً كاملة خارج الـ VPN — مباشرةً من شريط القوائم في ماك أو من علبة النظام في لينكس.**<br>
تبديل DNS بنقرة واحدة (Cloudflare وGoogle وغيرها)، اختبار سرعة Cloudflare، وإدارة خوادم التطوير.<br>
SwiftUI أصلي على ماك · GTK4 وlibadwaita أصلي على لينكس · مجاني ومفتوح المصدر · بلا حساب وبلا تتبع

[![تحميل لماك](https://img.shields.io/badge/macOS-Download%20DMG-0A84FF?style=for-the-badge&logo=apple&logoColor=white)](https://github.com/SajjadMohabati/DevNet/releases/latest/download/DevNet.dmg)
[![تحميل deb](https://img.shields.io/badge/Ubuntu%20%2F%20Debian-.deb-E95420?style=for-the-badge&logo=ubuntu&logoColor=white)](https://github.com/SajjadMohabati/DevNet/releases/latest)
[![تحميل rpm](https://img.shields.io/badge/Fedora%20%2F%20RHEL-.rpm-51A2DA?style=for-the-badge&logo=fedora&logoColor=white)](https://github.com/SajjadMohabati/DevNet/releases/latest)

[![أحدث إصدار](https://img.shields.io/github/v/release/SajjadMohabati/DevNet?style=flat-square&color=0A84FF)](https://github.com/SajjadMohabati/DevNet/releases/latest)
[![التحميلات](https://img.shields.io/github/downloads/SajjadMohabati/DevNet/total?style=flat-square&color=34C759)](https://github.com/SajjadMohabati/DevNet/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-34C759?style=flat-square)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/SajjadMohabati/DevNet?style=flat-square&color=FFD60A)](https://github.com/SajjadMohabati/DevNet/stargazers)

[English](README.md) · [فارسی](README.fa.md) · **العربية**

<img src="docs/hero.png" alt="لوحة DevNet: عنوان IP المحلي وعنوان مزود الإنترنت وعنوان كل VPN، المسارات، DNS، السرعة المباشرة والمشاريع العاملة">

</div>

<div dir="rtl">

## لماذا DevNet؟

الـ VPN متصل، والآن لا تعمل الشبكة الداخلية لشركتك أو بوابة جامعتك أو موقع البنك أو خادم الاختبار المحلي أو مواقع بلدك:
خطأ 403، انتهاء المهلة، كابتشا، أو بطء شديد. برنامج الـ VPN لديك إما لا يدعم تقسيم النفق، أو يدعمه «لكل تطبيق» فقط، أو
بقائمة ثابتة لا يمكن تعديلها.

فينتهي بك الأمر بلصق `sudo route add …` أو `sudo ip route add …` في الطرفية، وتلقي `File exists`، وفقدان كل شيء عند تغيير
شبكة Wi-Fi، دون أن تعرف أبداً أي عنوان IP يراه كل موقع.

**DevNet يحل ذلك بنقرة واحدة.** تطبيق صغير وأصلي يحافظ على مجموعة من المسارات عبر بوابة شبكتك المحلية، خارج أي VPN،
ويبقيها صحيحة مع تغيّر الشبكات واتصالات الـ VPN. نفس المزايا ونفس الواجهة على **ماك ولينكس**.

## المزايا

### 🔀 تقسيم نفق يعمل مع *أي* VPN
- **الشبكات** (`10.20.0.0/16`) و**المضيفات** و**النطاقات** (`intranet.example.com` أو رابط كامل) و**جميع عناوين دولة
  كاملة** تتجاوز الـ VPN.
- يعمل مع **WireGuard وOpenVPN وL2TP/IPsec وIKEv2 وProtonVPN وv2ray / Xray / sing-box في وضع TUN** وغيرها. لأن DevNet
  يعدّل جدول التوجيه في النظام، فلا يهمه أي عميل تستخدم ولا عدد الاتصالات المفتوحة.
- **إصلاح ذاتي:** كل مسار يحفظ الحالة التي *تريدها*، وDevNet يطابق الجدول الفعلي معها. النقرات السريعة وتغيير الشبكة
  والأخطاء الجزئية كلها تنتهي إلى الحالة الصحيحة.
- **يتبع شبكتك:** تُكتشف البوابة تلقائياً وتُفحص باستمرار؛ انتقل من شبكة المنزل إلى المكتب وستنتقل المسارات تلقائياً.
- حذف أي مسار مقيّد دائماً بالبوابة والواجهة اللتين أُضيف عليهما، فلا يحذف DevNet أبداً مساراً يخص الـ VPN.

### 🌐 كل عناوين IP في نظرة واحدة، حتى مع عدة VPN معاً
- **العنوان المحلي** و**عنوان مزود الإنترنت الحقيقي** والعنوان الذي **تراه المواقع الموجّهة** و**سطر لكل VPN متصل** مع
  عنوانه العام وواجهته (`utun4 · default`، `wg0`، `ppp0`…).
- نسخ أي عنوان بنقرة واحدة.

### 🧭 تبديل DNS يعمل فعلاً تحت الـ VPN
- إعدادات جاهزة لـ **Google وCloudflare** وخوادم أخرى، وأضف ما تريد.
- معظم برامج تغيير DNS تغيّر إعداد Wi-Fi فقط وتخسر أمام DNS الذي يفرضه الـ VPN. DevNet يطبّق الإعداد **على كل الاتصالات
  النشطة، بما فيها الـ VPN**، ويعيد الإعدادات الأصلية عند العودة إلى الوضع التلقائي.
- على لينكس يعمل مع **systemd-resolved** أو **NetworkManager** أو ملف `/etc/resolv.conf`، أيّاً كان ما تستخدمه توزيعتك.
- يعرض الـ DNS الذي يستخدمه النظام *فعلاً*، مع اختبار زمن الاستجابة لكل إعداد ومسح الذاكرة المؤقتة بنقرة.

### ⚡️ اختبار السرعة وزمن الاستجابة المباشر
- **اختبار سرعة Cloudflare** بنقرة واحدة (تنزيل، رفع، ping) مع رسم بياني مباشر وسجل. يقيس المسار الذي تسلكه حركتك فعلاً،
  عبر الـ VPN أو مباشرة.
- سرعة لحظية وزمن استجابة لأهدافك الخاصة ما دام DevNet مفتوحاً؛ لا شيء يعمل وهو مخفي.

### 🛠 مدير خوادم التطوير
- يعرض كل ما يستمع على منفذ، مجمّعاً حسب **مجلد المشروع** (Node وBun وDeno وPython وJava/Gradle وGo وRuby وPHP و.NET
  وPostgres وRedis وnginx…) مع **حاويات Docker وPodman**.
- افتح في VS Code أو Cursor أو IntelliJ أو مدير الملفات أو المتصفح؛ و**أوقف** أي عملية بنقرة، حتى التي يعاد تشغيلها بعد
  `kill`.

### ✨ أصلي على النظامين
- **ماك:** SwiftUI، لوحة بأسلوب مركز التحكم مع **Liquid Glass**، الوضعان الفاتح والداكن، اختصار عام (**⌃⇧I** افتراضياً،
  قابل للتغيير).
- **لينكس:** GTK4 وlibadwaita، أيقونة في علبة النظام مع نفس اللوحة المدمجة، وضع فاتح وداكن تلقائي، اختصار عام في GNOME،
  والأمر `devnet --panel` لربطه في أي سطح مكتب آخر.
- **أقل صلاحيات ممكنة:** على ماك يثبّت إدخال واحد لكلمة المرور قاعدة sudoers تسمح فقط بـ `route add/delete` وDNS؛ وعلى لينكس
  مساعد polkit صغير يقبل فقط عمليات المسارات وDNS بعد التحقق منها. لا شيء آخر يحصل على صلاحيات الجذر.
- خفيف وسريع: بلا Electron، بلا خدمات خلفية، بلا تتبع، بلا حساب. استهلاك المعالج في وضع الخمول قرابة الصفر.

## مقارنة مع الخيارات المعتادة

| | سكربتات `route` / `ip route` | تقسيم النفق في عميل VPN | تطبيقات تغيير DNS | **DevNet** |
|---|:-:|:-:|:-:|:-:|
| يعمل مع أي VPN وعدة اتصالات معاً | ⚠️ يدوي | ❌ نفقه فقط | — | ✅ |
| توجيه حسب النطاق / الرابط | ❌ | نادراً | — | ✅ |
| توجيه دولة كاملة بنقرة | ❌ | نادراً | — | ✅ |
| يتبع تغيير Wi-Fi / الشبكة | ❌ | ✅ | — | ✅ |
| عرض عنوان المزود وعنوان كل VPN | ❌ | ❌ | ❌ | ✅ |
| DNS يتغلب على DNS المفروض من VPN | — | — | ❌ | ✅ |
| اختبار سرعة على المسار الحقيقي | ❌ | ❌ | ❌ | ✅ |
| مدير خوادم التطوير والحاويات | ❌ | ❌ | ❌ | ✅ |
| نفس التطبيق على ماك ولينكس | ⚠️ | يختلف | نادراً | ✅ |
| بلا كلمة مرور وبأقل صلاحيات | ❌ | ✅ | ⚠️ | ✅ |
| أصلي وخفيف ومفتوح المصدر ومجاني | ✅ | يختلف | يختلف | ✅ |

## التثبيت

### ماك

1. **[حمّل DevNet.dmg](https://github.com/SajjadMohabati/DevNet/releases/latest/download/DevNet.dmg)**، افتحه واسحب
   **DevNet** إلى **Applications**.
2. افتح DevNet. لأنه مفتوح المصدر وغير موثّق من Apple، سيطلب macOS الإذن في المرة الأولى: اذهب إلى
   **System Settings › Privacy & Security** واضغط **Open Anyway**، أو نفّذ:

</div>

```bash
xattr -dr com.apple.quarantine /Applications/DevNet.app
```

<div dir="rtl">

3. اضغط أيقونة شريط القوائم (أو **⌃⇧I**). في نافذة DevNet اضغط **Enable Passwordless Mode** مرة واحدة.

المتطلبات: macOS 26 Tahoe أو أحدث، Apple silicon أو Intel.

### لينكس

حمّل الحزمة المناسبة لتوزيعتك من **[أحدث إصدار](https://github.com/SajjadMohabati/DevNet/releases/latest)**، ثم:

</div>

```bash
# Debian 12+ / Ubuntu 22.10+ / Linux Mint / Pop!_OS
sudo apt install ./devnet_1.3.0_all.deb

# Fedora 37+ / RHEL 9 (EPEL) / Rocky / AlmaLinux
sudo dnf install ./devnet-1.3.0-1.noarch.rpm
```

<div dir="rtl">

ثم شغّل **DevNet** من قائمة التطبيقات أو بالأمر `devnet`. في GNOME فعّل إضافة
**AppIndicator and KStatusNotifierItem Support** لرؤية أيقونة علبة النظام؛ كل شيء آخر يعمل بدونها.

أو التثبيت من المصدر:

</div>

```bash
git clone https://github.com/SajjadMohabati/DevNet.git
sudo ./DevNet/linux/install.sh   # أو ./DevNet/linux/run.sh للتجربة دون تثبيت
```

<div dir="rtl">

تفاصيل الحزم وحل المشكلات ونموذج الأمان في [`linux/README.md`](linux/README.md).

### بناء نسخة ماك من المصدر

</div>

```bash
git clone https://github.com/SajjadMohabati/DevNet.git
cd DevNet
./build.sh             # بناء شامل وتثبيت في /Applications
sudo ./install.sh      # اختياري: وضع بلا كلمة مرور + مساعد DNS
./release.sh           # اختياري: إنشاء ملف DMG
```

<div dir="rtl">

يحتاج فقط إلى **Xcode Command Line Tools**؛ بلا مشروع Xcode وبلا اعتماديات.

## كيف يعمل

| | ماك | لينكس |
|---|---|---|
| المسارات | `route(8)` عبر بوابة الشبكة المحلية؛ يُطبَّق الفرق فقط بين المطلوب والفعلي | `ip route` عبر مساعد polkit يتحقق من كل CIDR وبوابة وواجهة |
| اكتشاف VPN | `scutil --nc` و`netstat` | `ip` وNetworkManager (`nmcli`) |
| العناوين العامة | `curl --interface` لكل واجهة | طلب HTTPS مرتبط بعنوان كل واجهة |
| DNS | المساعد `devnet-dns` يكتب إعدادات DNS لكل خدمة (مع نسخة احتياطية) عبر `scutil` | `resolvectl` (systemd-resolved) أو `nmcli` (NetworkManager) أو `/etc/resolv.conf` |
| الصلاحيات | ملف `/etc/sudoers.d/devnet` للأوامر أعلاه فقط | إجراء polkit لـ `/usr/libexec/devnet/devnet-helper` فقط |

تُحفظ بياناتك محلياً بصيغة JSON بسيطة (`~/Library/Application Support/VPNRoutes/` على ماك و`~/.config/devnet/` على لينكس).

## أسئلة شائعة

**هل DevNet شبكة VPN؟** لا. DevNet يحدد أي حركة مرور *تتجاوز* الـ VPN. استخدمه مع الـ VPN الذي لديك.

**هل تتسرب حركة المرور؟** فقط الوجهات التي تضيفها بنفسك تمر خارج الـ VPN؛ كل شيء آخر يبقى داخل النفق.

**هل يمكن تمرير كل مواقع دولة معينة خارج الـ VPN؟** نعم: *Add › Country IP Ranges…* ثم رمز الدولة (ISO). هكذا تبقى
المواقع التي ترفض العناوين الأجنبية (403) تعمل والـ VPN متصل.

**أستخدم v2rayN / v2rayNG / Hiddify / Nekoray وما زالت المواقع ترى عنواناً أجنبياً.** هذه العملاء غالباً تفعّل **وكيل
النظام (system proxy)**، والتطبيقات التي تستخدمه (ومنها المتصفح) ترسل الحركة إليه مباشرة، فلا يستطيع أي جدول توجيه تغيير
مسارها. أوقف وكيل النظام واستخدم **وضع TUN**، أو أضف قاعدة `geoip` للدولة → direct في العميل. في وضع TUN تعمل مسارات DevNet
بشكل طبيعي.

**هل يعمل على Wayland؟** نعم. نسخة لينكس مبنية على GTK4، وأيقونة علبة النظام تستخدم بروتوكول StatusNotifierItem القياسي
(KDE وCinnamon وXFCE وBudgie وGNOME مع إضافة AppIndicator).

**ماذا يغيّر الوضع بلا كلمة مرور على ماك؟** ملف sudoers واحد يسمح بـ `route add/delete` و`networksetup -setdnsservers`
ومسح ذاكرة DNS ومساعد DNS فقط. احذفه بـ `sudo ./install.sh --uninstall`.

## المساهمة

البلاغات وطلبات الدمج مرحّب بها. إذا وفّر لك DevNet الوقت، **⭐ أضف نجمة للمستودع** ليجده الآخرون.

## المطوّر

من تطوير **[سجاد محبتي (Sajjad Mohabati)](https://github.com/SajjadMohabati)** · [github.com/SajjadMohabati/DevNet](https://github.com/SajjadMohabati/DevNet)

منشور بموجب [رخصة MIT](LICENSE). أيقونات نسخة لينكس مبنية على [Lucide](https://lucide.dev) (ISC).

<sub>كلمات مفتاحية: تقسيم نفق VPN على ماك ولينكس، تقسيم النفق على أوبونتو، تجاوز VPN، استثناء عنوان IP من VPN، توجيه نطاق
خارج VPN، إدارة المسارات الثابتة، واجهة رسومية لـ ip route، تغيير DNS على ماك ولينكس، v2ray وضع TUN، WireGuard split tunnel،
أداة شبكة لشريط القوائم، اختبار سرعة Cloudflare، أدوات المطورين، إدارة خوادم التطوير المحلية.</sub>

</div>
