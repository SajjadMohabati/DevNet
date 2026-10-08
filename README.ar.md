<div align="center">

<img src="docs/icon.png" width="128" alt="أيقونة DevNet — تقسيم نفق VPN على ماك">

# DevNet — تقسيم نفق VPN وتجاوزه على macOS

**مرّر الشبكات والنطاقات ودولاً كاملة خارج الـ VPN — مباشرةً من شريط القوائم.**<br>
بالإضافة إلى تبديل DNS بنقرة واحدة (Cloudflare وGoogle وغيرها) وإدارة خوادم التطوير.<br>
SwiftUI أصلي · Liquid Glass · macOS 26 Tahoe · Apple silicon وIntel · مجاني ومفتوح المصدر

[![تحميل DMG](https://img.shields.io/badge/Download-DevNet.dmg-0A84FF?style=for-the-badge&logo=apple&logoColor=white)](https://github.com/SajjadMohabati/DevNet/releases/latest/download/DevNet.dmg)
[![macOS 26+](https://img.shields.io/badge/macOS-26%20Tahoe%2B-black?style=for-the-badge&logo=apple)](#المتطلبات)
[![License: MIT](https://img.shields.io/badge/License-MIT-34C759?style=for-the-badge)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/SajjadMohabati/DevNet?style=for-the-badge&color=FFD60A)](https://github.com/SajjadMohabati/DevNet/stargazers)

[English](README.md) · [فارسی](README.fa.md) · **العربية**

<img src="docs/hero.png" alt="لوحة DevNet في شريط القوائم: عنوان IP المحلي وعنوان مزود الإنترنت وعنوان كل VPN، المسارات، DNS والمشاريع العاملة">

</div>

<div dir="rtl">

## لماذا DevNet؟

الـ VPN متصل، والآن لا تعمل الشبكة الداخلية لشركتك أو بوابة جامعتك أو موقع البنك أو خادم الاختبار المحلي أو مواقع بلدك —
خطأ 403، انتهاء المهلة، كابتشا، أو بطء شديد. برنامج الـ VPN لديك إما لا يدعم تقسيم النفق على ماك، أو يدعمه «لكل تطبيق»
فقط، أو بقائمة ثابتة لا يمكن تعديلها.

فينتهي بك الأمر بلصق `sudo route add …` في الطرفية، وتلقي `File exists`، وفقدان كل شيء عند تغيير شبكة Wi-Fi، دون أن
تعرف أبداً أي عنوان IP يراه كل موقع.

**DevNet يحل ذلك بنقرة واحدة.** تطبيق صغير وأصلي في شريط القوائم يحافظ على مجموعة من المسارات عبر بوابة شبكتك المحلية —
خارج أي VPN — ويبقيها صحيحة مع تغيّر الشبكات.

## المزايا

### 🔀 تقسيم نفق يعمل مع *أي* VPN
- **الشبكات** (`10.20.0.0/16`) و**المضيفات** و**النطاقات** (`intranet.example.com` أو رابط كامل) و**جميع عناوين دولة
  كاملة** (من ipdeny.com) تتجاوز الـ VPN.
- يعمل مع **WireGuard وOpenVPN وL2TP/IPsec وIKEv2 وProtonVPN…** — لأن DevNet يعدّل جدول التوجيه في النظام، فلا يهمه أي
  عميل تستخدم ولا عدد الاتصالات المفتوحة.
- **إصلاح ذاتي:** كل مسار يحفظ الحالة التي *تريدها*، وDevNet يطابق الجدول الفعلي معها. النقرات السريعة وتغيير الشبكة
  والأخطاء الجزئية كلها تنتهي إلى الحالة الصحيحة.
- **يتبع شبكتك:** تُكتشف البوابة تلقائياً وتُفحص كل 10 ثوانٍ؛ انتقل من شبكة المنزل إلى المكتب وستنتقل المسارات تلقائياً.

### 🌐 كل عناوين IP في نظرة واحدة — حتى مع عدة VPN معاً
- **العنوان المحلي** و**عنوان مزود الإنترنت الحقيقي** والعنوان الذي **تراه المواقع الموجّهة** و**سطر لكل VPN متصل**
  مع عنوانه العام وواجهته (`utun4 · default`، `ppp0`…).
- نسخ أي عنوان بنقرة واحدة.

### 🧭 تبديل DNS يعمل فعلاً تحت الـ VPN
- إعدادات جاهزة لـ **Google وCloudflare** وغيرها — وأضف ما تريد.
- معظم برامج تغيير DNS تغيّر إعداد Wi-Fi فقط وتخسر أمام DNS الذي يفرضه الـ VPN. المساعد الصغير في DevNet يغيّره
  **مباشرة على كل الخدمات، بما فيها الـ VPN**، ويعيد الإعدادات الأصلية عند العودة إلى الوضع التلقائي.
- يعرض الـ DNS الذي يستخدمه النظام *فعلاً*، مع اختبار السرعة ومسح الذاكرة المؤقتة بنقرة.

### 🛠 مدير خوادم التطوير
- يعرض كل ما يستمع على منفذ، مجمّعاً حسب **مجلد المشروع** (Node وBun وDeno وPython وJava/Gradle وGo وRuby وPHP و.NET
  وPostgres وRedis وnginx…) مع **حاويات Docker**.
- افتح في VS Code أو Cursor أو IntelliJ أو Finder أو المتصفح؛ و**أوقف** أي عملية بنقرة — حتى التي يعيد LaunchAgent تشغيلها.

### ✨ كأنه جزء من macOS
- **SwiftUI** أصلي، لوحة بأسلوب مركز التحكم مع **Liquid Glass**، الوضعان الفاتح والداكن.
- اختصار عام **⌃⇧I** يفتح اللوحة من أي مكان، حتى لو كانت الأيقونة مخفية خلف النوتش.
- **وضع بلا كلمة مرور:** إدخال واحد لكلمة المرور يثبّت قاعدة sudoers تسمح فقط بـ `route add/delete` وإعدادات DNS ومسح
  الذاكرة المؤقتة. لا شيء آخر يحصل على صلاحيات الجذر.
- نحو 2 ميغابايت، ثنائي شامل، بلا Electron، بلا خدمات خلفية، بلا تتبع، بلا حساب. تشغيل عند الدخول.

## مقارنة مع الخيارات المعتادة

| | سكربتات `route` | تقسيم النفق في عميل VPN | تطبيقات تغيير DNS | **DevNet** |
|---|:-:|:-:|:-:|:-:|
| يعمل مع أي VPN وعدة اتصالات معاً | ⚠️ يدوي | ❌ نفقه فقط | — | ✅ |
| توجيه حسب النطاق / الرابط | ❌ | نادراً | — | ✅ |
| توجيه دولة كاملة بنقرة | ❌ | نادراً | — | ✅ |
| يتبع تغيير Wi-Fi / الشبكة | ❌ | ✅ | — | ✅ |
| عرض عنوان المزود وعنوان كل VPN | ❌ | ❌ | ❌ | ✅ |
| DNS يتغلب على DNS المفروض من VPN | — | — | ❌ | ✅ |
| مدير خوادم التطوير وDocker | ❌ | ❌ | ❌ | ✅ |
| بلا كلمة مرور وبأقل صلاحيات | ❌ | ✅ | ⚠️ | ✅ |
| أصلي وخفيف ومفتوح المصدر ومجاني | ✅ | يختلف | يختلف | ✅ |

## التثبيت

1. **[حمّل DevNet.dmg](https://github.com/SajjadMohabati/DevNet/releases/latest/download/DevNet.dmg)**، افتحه واسحب
   **DevNet** إلى **Applications**.
2. افتح DevNet. لأنه مفتوح المصدر وغير موثّق من Apple، سيطلب macOS الإذن في المرة الأولى: اذهب إلى
   **System Settings › Privacy & Security** واضغط **Open Anyway** — أو نفّذ:

</div>

```bash
xattr -dr com.apple.quarantine /Applications/DevNet.app
```

<div dir="rtl">

3. اضغط أيقونة شريط القوائم (أو **⌃⇧I**). في نافذة DevNet اضغط **Enable Passwordless Mode** مرة واحدة.

### البناء من المصدر

</div>

```bash
git clone https://github.com/SajjadMohabati/DevNet.git
cd DevNet
./build.sh             # بناء شامل وتثبيت في /Applications
sudo ./install.sh      # اختياري: وضع بلا كلمة مرور + مساعد DNS
./release.sh           # اختياري: إنشاء ملف DMG
```

<div dir="rtl">

يحتاج فقط إلى **Xcode Command Line Tools** — بلا مشروع Xcode وبلا اعتماديات.

## المتطلبات

macOS 26 Tahoe أو أحدث · Apple silicon أو Intel

## أسئلة شائعة

**هل DevNet شبكة VPN؟** لا. DevNet يحدد أي حركة مرور *تتجاوز* الـ VPN. استخدمه مع الـ VPN الذي لديك.

**هل تتسرب حركة المرور؟** فقط الوجهات التي تضيفها بنفسك تمر خارج الـ VPN؛ كل شيء آخر يبقى داخل النفق.

**هل يمكن تمرير كل مواقع دولة معينة خارج الـ VPN؟** نعم — *Add › Country IP Ranges…* ثم رمز الدولة (ISO). هكذا تبقى
المواقع التي ترفض العناوين الأجنبية (403) تعمل والـ VPN متصل.

**ماذا يغيّر الوضع بلا كلمة مرور؟** ملف sudoers واحد يسمح بـ `route add/delete` و`networksetup -setdnsservers` ومسح ذاكرة
DNS ومساعد DNS فقط. احذفه بـ `sudo ./install.sh --uninstall`.

## المساهمة

البلاغات وطلبات الدمج مرحّب بها. إذا وفّر لك DevNet الوقت، **⭐ أضف نجمة للمستودع** ليجده الآخرون.

## المطوّر

من تطوير **[سجاد محبتي (Sajjad Mohabati)](https://github.com/SajjadMohabati)** · [github.com/SajjadMohabati/DevNet](https://github.com/SajjadMohabati/DevNet)

منشور بموجب [رخصة MIT](LICENSE).

<sub>كلمات مفتاحية: تقسيم نفق VPN على ماك، تجاوز VPN، استثناء عنوان IP من VPN، توجيه نطاق خارج VPN، إدارة المسارات الثابتة،
تغيير DNS على ماك، WireGuard split tunnel، أداة شبكة لشريط القوائم، أدوات المطورين، إدارة خوادم التطوير المحلية.</sub>

</div>
