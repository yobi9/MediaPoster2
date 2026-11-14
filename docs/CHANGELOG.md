# Changelog

جميع التغييرات الملحوظة في هذا المشروع ستُوثَّق في هذا الملف.
التنسيق مستوحى من [Keep a Changelog](https://keepachangelog.com/).

## [1.0.1] - 2026-11-15

### أُصلح (Fixed)
- dry-run مع output_root: لا مزيد من ERROR لكل عنصر
- CLI: أخطاء الإعداد تعيد رمز 2 بدل UnboundLocalError
- CLI: `--dry-run`/`--convert-only` ثلاثية الحالة (تحفظ إعدادات GUI)
- TMDBClient: لا يقرأ config.json من القرص (يمرر sizes/TTL صراحةً)
- cache: `_dirty` لا يُمسح إلا بعد كتابة ناجحة
- worker: يمرر negative_cache_ttl_days, poster_size, backdrop_size
- ItemResult.target_dir: مجلد الإخراج الحقيقي
- main_window: عدّاد "ملغى" + فتح مجلد صحيح
- scanner: "specials"/"special" مجلد إضافات، لا موسم
- title_cleaner: توثيق مقايضة jargon (بلا تغيير سلوكي)

### تغيّر (Changed)
- رفع الإصدار إلى 1.0.1
- build.bat: بناء واحد، إصدار من مصدر واحد (app/config.py)، بوابة pytest، تنظيف dist
- MediaArtAutoSync.spec: excludes + ترجمات مختصرة ⇒ 45.4 MB → 29.0 MB (−36.15%)
- لا إصدار CLI منفصل: `--cli` مدمج في exe الواحد

### أُضيف (Added)
- build_release.bat: إنتاج Portable (مجلد + zip + SHA256SUMS.txt)
- installer/mediaart.iss + build_installer.bat: معالج تثبيت Next → Next → Finish (عربي + إنجليزي)
- +15 دالة اختبار جديدة (181 → 196)؛ و`pytest` يجمع 230 حالة (ملاحظات إصدار v1.0.0 المنشورة تذكر 215)
- ثلاثة مخرجات للتوزيع: ملف تنفيذي (~29 MB)، حزمة محمولة (~28.7 MB)، معالج تثبيت (~30.7 MB)

### قيود معروفة (Known Limitations)
- `--cli` من الـexe المعبّأ ينتج بلا مخرجات مرئية (console=False). للاستخدام البرمجي: من المصدر، أو عبر قراءة app_log.txt.
- كل بناء يُنتج SHA256 مختلفاً (PyInstaller غير قابل لإعادة الإنتاج byte-for-byte). استخدم بصمة البناء المنشور.
- لا توقيع رقمي: تحذير SmartScreen متوقع على أجهزة Windows.
- لا تحديث تلقائي.
- اختبار التثبيت على جهاز نظيف (Next → Next → Finish → تشغيل → إلغاء تثبيت) ما زال مطلوباً ولم يُنفَّذ بعد.
