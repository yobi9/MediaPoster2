# دليل المطوّر والوكيل البرمجي — MediaArt Auto-Sync

> **الجمهور:** المطوّرون والوكلاء البرمجيون (AI agents) الذين سيواصلون بناء هذا المشروع.
> **اللغة:** الشرح بالعربية، وأسماء الملفات والدوال والثوابت بالإنجليزية كما هي في الكود.
> **الحالة:** الإصدار `1.0.1` — مكتمل ومُختبر (230 اختباراً ناجحاً على Python 3.14.7).

---

## 1. نظرة عامة

MediaArt Auto-Sync تطبيق سطح مكتب مكتوب بـ Python. يفحص مكتبة وسائط محلية، يستخرج عناوين
الأفلام والمسلسلات من أسماء المجلدات، يبحث عنها في TMDB، ثم ينزّل الملصق العمودي والخلفية
الأفقية ويحفظهما بأسماء قياسية داخل مجلد كل عمل. كما يحوّل صور `.webp` الموجودة إلى `.jpg`
عالي الجودة.

المبدأ المعماري الحاكم:

> **المنطق الأساسي (core) لا يعتمد على Qt إطلاقاً.** الواجهة الرسومية طبقة اختيارية فوقه،
> وسطر الأوامر طبقة أخرى. أي سلوك جديد يجب أن يعيش في `app/services/` أو `app/config.py`
> ليظل قابلاً للاختبار وللاستخدام بلا واجهة.

---

## 2. التشغيل السريع للمطوّر

```bat
cd /d <path-to-project>

REM بيئة جاهزة مسبقاً في هذا المشروع:
.venv\Scripts\python.exe main.py
.venv\Scripts\python.exe main.py --cli --help

REM الاختبارات (لا تحتاج مفتاح TMDB ولا إنترنت):
.venv\Scripts\python.exe -m pytest -q

REM تشغيل الواجهة بلا شاشة (للتحقق الآلي):
set QT_QPA_PLATFORM=offscreen
.venv\Scripts\python.exe main.py
```

تثبيت من الصفر: `setup.bat` ثم `run.bat`. المتطلبات في `requirements.txt`، وأدوات التطوير في
`requirements-dev.txt`.

**بيئة مرجعية مُختبرة:** Windows 10/11، Python 3.14.7، PyQt6 6.12.0، Pillow 13.0.0، requests 2.34.2.

---

## 3. شجرة المشروع

```text
MediaPoster/
├── main.py                     # نقطة الدخول (Double-click / python main.py)
├── app/
│   ├── __main__.py             # python -m app
│   ├── main.py                 # التوجيه: GUI افتراضياً، CLI عند --cli/--help/--version
│   ├── config.py               # AppConfig، مسارات البيانات، حفظ/تحميل، resolve_token
│   ├── errors.py               # MediaArtError ووراثاتها
│   ├── logging_setup.py        # تسجيل دوّار + RedactionFilter + get_logger
│   ├── models.py               # MediaKind, Status, MediaItem, TMDBMatch, ItemResult, RunSummary
│   ├── cli.py                  # وضع headless + argparse
│   ├── services/
│   │   ├── title_cleaner.py    # تنظيف الأسماء + normalize_for_match
│   │   ├── scanner.py          # اكتشاف الأفلام/المسلسلات
│   │   ├── tmdb.py             # عميل TMDB، المصادقة، التقييم، الصور، retries
│   │   ├── cache.py            # JsonCache مع TTL
│   │   ├── images.py           # التنزيل، التحويل، الكتابة الذرية
│   │   ├── manifest.py         # سجل شجرة الإخراج (output_root)
│   │   └── processor.py        # تنسيق العملية الكاملة
│   └── ui/
│       ├── main_window.py      # الواجهة الكاملة
│       ├── worker.py           # RunWorker, PingWorker, QtLogHandler
│       └── theme.py            # QSS داكن + أيقونة مرسومة
├── tests/                      # 230 اختباراً (pytest)
├── docs/
│   ├── DEVELOPER_GUIDE.md      # هذا الملف
│   └── PLAN.md                 # خطة البناء والمراحل
├── README.md                   # دليل المستخدم النهائي (عربي)
├── config.example.json         # مثال لكل مفاتيح AppConfig
├── requirements.txt
├── requirements-dev.txt
├── setup.bat
├── run.bat
└── .gitignore
```

---

## 4. خريطة الوحدات والمسؤوليات

| الوحدة | المسؤولية | يجب ألا تفعل |
|---|---|---|
| `app/main.py` | اختيار GUI أو CLI، إعداد QApplication، excepthook | أي منطق أعمال |
| `app/cli.py` | تحويل argv إلى `AppConfig`، تشغيل `discover_media` + `Processor` | تنزيل مباشر أو regex |
| `app/config.py` | الحقول، الحدود، المسارات، التوكن، التخزين الذري | الاتصال بالشبكة |
| `app/logging_setup.py` | تهيئة `mediaart` logger مرة واحدة، إخفاء الأسرار | طباعة مباشرة إلى stdout |
| `app/models.py` | DTOs و enums وحسابات الملخص | I/O أو شبكة |
| `title_cleaner.py` | تحويل الاسم الخام إلى `CleanedTitle(title, year)` | معرفة بنية المجلدات |
| `scanner.py` | المشي في الشجرة وقرار movie/series/item | تنزيل أو كتابة صور |
| `tmdb.py` | HTTP، المصادقة، البحث، التقييم، اختيار الصور | كتابة ملفات على القرص |
| `cache.py` | تخزين نتائج البحث في JSON مع TTL | حفظ التوكن أو الصور |
| `images.py` | تنزيل، تحقق، تحويل، كتابة ذرية، حذف WebP بأمان | البحث في TMDB |
| `processor.py` | ترتيب الخطوات، حالات النتيجة، الرسائل | تفاصيل HTTP أو regex |
| `ui/main_window.py` | ربط الحالة والإعدادات والأحداث | استدعاء الشبكة على الخيط الرئيسي |
| `ui/worker.py` | تنفيذ العمل على `QThread` وبث الإشارات | لمس عناصر الواجهة مباشرة |

---

## 5. مسار البيانات (Data Flow)

```text
argv / GUI
   │
   ▼
AppConfig  ──(resolve_token: env ثم config)──►  token
   │
   ▼
discover_media(root, media_filter)          [scanner.py]
   │  قائمة MediaItem (movie | series)
   ▼
Processor.run(items, should_cancel, on_item, on_progress)   [processor.py]
   │
   ├─ 1) convert_webp_in_folder(...)        [images.py]  (قبل أي شبكة)
   ├─ 2) إن كان convert_only → نتيجة محلية وانتهى
   ├─ 3) فحص وجود poster/fanart/background
   ├─ 4) TMDBClient.find_match(item)        [tmdb.py → cache.py]
   │       └─ search → score → enrich images → cache
   ├─ 5) ImageService.save_image(...)       [images.py]
   │       └─ download → validate → atomic write → mirror names
   └─ 6) ItemResult + تحديث RunSummary
   │
   ▼
GUI: جدول + عدادات + سجل حي   |   CLI: ملخص + تفاصيل + exit code
```

نقاط مهمة:

- التحويل المحلي يسبق البحث الشبكي، لذا يعمل حتى لو فشل TMDB.
- `Processor` هو المكان الوحيد الذي يقرر حالة العنصر (`OK`, `PARTIAL`, `SKIPPED`, `NOT_FOUND`, `ERROR`).
- `on_item` يُستدعى بعد كل عنصر، و`on_progress` قبل/بعد كل عنصر. الواجهة لا تعرف شيئاً عن HTTP.

---

## 6. ثوابت يجب عدم كسرها (Invariants)

هذه قواعد عمل، وليست تفضيلات. أي تغيير عليها يجب أن يحدّث الاختبارات وهذا الملف و`README.md`.

1. **المسلسل يُعالج مرة واحدة فقط** عند مجلد المسلسل الأب. لا تُكتب صور داخل مجلد موسم أو حلقة.
2. **عند اكتشاف مسلسل، يتوقف النزول** (`dirnames[:] = []`) فلا تكرار ولا صور موسمية.
3. **لا تُحذف `.webp` إلا بعد نجاح كتابة JPG صالح.** الحذف فشل ≠ فشل التحويل.
4. **كل كتابة ملف ذرية**: ملف مؤقت في نفس المجلد ثم `os.replace`. لا كتابة مباشرة على الهدف.
5. **الصور الموجودة لا تُستبدل افتراضياً.** `overwrite_images=False` هو الافتراضي.
6. **صور JPEG القادمة من TMDB تُنسخ بايتاتها كما هي** إن كانت RGB/L وغير متحركة؛ لا إعادة ضغط بلا داع.
7. **الشفافية تُسطّح على الأبيض**، لا على الأسود.
8. **التوكن لا يظهر في السجلات ولا في الاستثناءات المطبوعة.** `RedactionFilter` يحجب `api_key=` و`Bearer` و`token=`.
9. **لا شبكة في خيط الواجهة الرئيسي.** كل I/O داخل `RunWorker`/`PingWorker`.
10. **الإلغاء تعاوني**: يُفحص بين العناصر وأثناء تنزيل الصورة. لا `terminate()` إلا عند الإغلاق القسري بعد مهلة.
11. **المكتبة المسطحة غير مدعومة**: ملفات فيديو مباشرة في مجلد فئة تُتجاهل مع تحذير.
12. **`AppConfig` يتحمل ملفاً تالفاً أو مفاتيح مجهولة** دون منع الإقلاع.

---

## 7. اكتشاف الوسائط — `scanner.py`

### 7.1 الامتدادات والمعالجات المسبقة

- امتدادات الفيديو: `mkv, mp4, avi, mov, m4v, wmv, flv, webm, mpg, mpeg, m2ts, ts, vob, iso`.
- تُستبعد ملفات العينات/الإعلانات عبر `_SAMPLE_RE`: `sample`, `trailer`, `teaser`, `featurette`, `behind the scenes`.
- تُستبعد المجلدات: المخفية (`.`) و`$` و`@`، وقائمة `_IGNORED_DIRS` (مثل `subs`, `artwork`, `metadata`, `nfo`, `sample`, `trailers`).
- الحد الأقصى للعمق `MAX_DEPTH = 15`، مع حماية من الحلقات عبر `resolve()` + `visited`.
- لا تتبع الروابط الرمزية (`followlinks=False`).

> **قيد معروف**: `os.walk` بلا `onerror` يبتلع `PermissionError` بصمت، فالمجلد الذي لا
> يمكن قراءته يختفي من الفحص **دون أي تحذير**. يُعالَج ضمن عمل تشخيص الاكتشاف (§9.4).

### 7.2 جدول قرار النوع

| الحالة في المجلد الحالي | القرار | ما يحدث |
|---|---|---|
| لا فيديو مباشر | حاوية | يستمر النزول |
| فيديو مباشر + مجلد موسم/حلقة | **مسلسل** | يُضاف (حسب الفلتر) ثم يُقطع النزول |
| فيديو مباشر + اسم فيديو فيه `SxxEyy` / `1x01` / `الحلقة 1` | **مسلسل** | كما أعلاه |
| فيديو مباشر فقط، والاسم ليس فئة عامة، وليس جذر مكتبة متعدد الملفات | **فيلم** | يُضاف ثم يُقطع النزول |
| فيديو مباشر داخل اسم فئة (`Movies`, `TV`, `أفلام`, …) أو جذر فيه أكثر من فيديو | **مكتبة مسطحة** | تحذير وتخطٍّ |
| الجذر نفسه اسمه `Season 1` أو `S01E01` | مرفوض | تحذير وإرجاع قائمة فارغة |
| مسلسل لكن `media_filter="movies"` | مستبعد | لا يظهر في النتائج |
| فيلم لكن `media_filter="series"` | مستبعد | لا يظهر في النتائج |

أنماط التعرف:

- `looks_like_season_dir`: `Season 1`, `S02`, `Series 3`, `الموسم الأول` … (لكن ليس `Se7en`).
- مجلدات الإضافات (`Specials`, `Featurettes`, `Behind the Scenes`, …) تُتجاهل: `Specials`
  ليس موسماً، واعتباره كذلك يحوّل الفيلم إلى مسلسل خطأً.
- `looks_like_episode_dir`: `S01E01`, `S01`, `1x03`, `Episode 2`, `الحلقة 2`.
- `has_episode_marker`: نفس الأنماط داخل اسم ملف الفيديو.

> ملاحظة: `S01` قد يُعتبر مجلد موسم أو حلقة؛ كلاهما يؤدي إلى اعتبار الأب مسلسلاً، وهو المطلوب.

### 7.3 بناء العنصر

`_build_item(folder, kind, videos)`:

1. `clean_title(folder.name)`.
2. إن لم يُستخرج عنوان، يجرّب `clean_title(videos[0].name)`.
3. إن فشل الاثنان، يُسجّل تحذيراً ويعيد `None`.
4. النتيجة `MediaItem(path=folder, kind, title, year, raw_name=folder.name)`.

النتائج تُرتّب أبجدياً حسب `str(path).casefold()`.

---

## 8. منظّف العناوين — `title_cleaner.py`

### 8.1 خط الأنابيب في `clean_title`

```text
raw
 ├─ إزالة امتداد الفيديو
 ├─ إزالة بادئة موقع (www.site.com -)
 ├─ استبدال _ . + بمسافات
 ├─ استخراج آخر سنة صالحة (1888 .. السنة الحالية + 2)   → year
 ├─ إزالة محتوى الأقواس [ ] ( ) { }
 ├─ اكتشاف مؤشر مسلسل (SxxEyy / 1x01 / season / الموسم …)
 ├─ إزالة مؤشرات الحلقات والمواسم
 ├─ إن وُجد مؤشر مسلسل: إزالة complete/كامل/كاملة
 ├─ إن وُجد مؤشر إصدار: إزالة extended/uncut/unrated
 ├─ إزالة H26x والأبعاد ومعدل البت وقنوات الصوت
 ├─ إزالة مصطلحات _TAG_TERMS (الأطول أولاً)
 ├─ إن وُجد مؤشر إصدار: إزالة ذيل المجموعة بعد -/@ أو كلمة UPPERCASE أخيرة
 ├─ إزالة بادئة فيلم/مسلسل العربية
 ├─ توحيد المسافات والقص عند 200 حرف
 └─ CleanedTitle(title, year)
```

خصائص مهمة:

- `_TAG_TERMS` **بيانات وليس كوداً**: أضف المصطلح الجديد إلى الصفوف المناسبة، ثم أضف اختباراً.
- المطابقة على حدود الكلمات `(?<![\w]) ... (?![\w])`، لذا `HD` لا يفسد كلمة داخلية.
- الأقواس تُزال **بعد** استخراج السنة، لذلك `(2014)` تُستخدم ثم تختفي.
- `MAX_YEAR` متحرك، فلا تُرفض سنوات المستقبل القريبة.
- إذا كان الاسم سنة فقط (`2012`)، يعيد المحاولة دون استخراج السنة ويحتفظ بالعنوان.
- أمثلة مرجعية موجودة كـ doctest:
  - `Breaking.Bad.S01.1080p.BluRay.x264-Arabic` → `Breaking Bad`
  - `[YTS] Interstellar (2014) [1080p] [BluRay]` → `Interstellar`, `2014`

### 8.2 `normalize_for_match`

تُستخدم لمقارنة عنوان المكتبة بعنوان TMDB:

1. `NFKD` ثم حذف علامات التركيب.
2. طيّ الحروف العربية: `أإآٱ→ا`, `ىئ→ي`, `ؤ→و`, `ة→ه`, `ﻻ→لا`.
3. حذف التشكيل (`\u064B-\u065F`, `\u0670`).
4. `casefold()`.
5. `&` → `and`.
6. حذف `' ’ \` ´`.
7. تحويل كل ما ليس حرفاً/رقماً إلى مسافة، ثم ضغط المسافات.

بهذا يتطابق `المومياء` مع `المومياء`، و`Fast & Furious` مع `Fast and Furious`.

### 8.3 إضافة قاعدة جديدة — الوصفة

1. أضف المصطلح إلى `_TAG_TERMS` (أو regex مخصص إذا كان نمطياً).
2. أضف حالة في `tests/test_title_cleaner.py` تُثبت:
   - إزالة المصطلح،
   - عدم إزالة كلمة مشابهة داخل عنوان حقيقي.
3. شغّل `pytest -q`.
4. حدّث قسم "تنقية الأسماء" في `README.md` فقط إذا تغيّر سلوك مرئي للمستخدم.

---

## 9. عميل TMDB — `tmdb.py`

### 9.1 المصادقة

يدعم نمطين تلقائياً:

| النمط | الكشف | الإرسال |
|---|---|---|
| v3 API Key | 32 حرفاً عادةً | `?api_key=...` |
| v4 Read Access Token | نقطتان وطول > 60، أو طول > 50 | `Authorization: Bearer ...` |

- `resolve_token` في `config.py` يعطي **الأولوية لمتغيرات البيئة** بالترتيب:
  `TMDB_API_KEY` ثم `TMDB_READ_ACCESS_TOKEN` ثم `TMDB_TOKEN`، وأخيراً `config.tmdb_api_key`.
- التوكن الفارغ يرفع `TMDBAuthError` عند بناء العميل.
- لا يُسجَّل التوكن أبداً؛ انظر `RedactionFilter`.

### 9.2 نقاط النهاية

| الغرض | المسار |
|---|---|
| اختبار الاتصال | `GET /configuration` |
| بحث فيلم | `GET /search/movie` |
| بحث مسلسل | `GET /search/tv` |
| صور إضافية | `GET /{movie|tv}/{id}/images` |

بارامترات البحث: `query`, `language`, `include_adult=false`, `page=1`، و`year` للأفلام أو
`first_air_date_year` للمسلسلات إن توفرت السنة.

### 9.3 التقييم (Scoring)

`score_candidate` يحسب لكل نتيجة:

| الحالة | النقاط |
|---|---|
| تطابق تام بعد التطبيع | 100 |
| بادئة لأحد الطرفين | 58 |
| احتواء جزئي | 42 |
| تشابه `SequenceMatcher ≥ 0.72` | `ratio × 58` |
| تشابه أقل | 0 (يُستبعد) |
| فرق سنة = 0 | +35 |
| فرق سنة = 1 | +18 |
| فرق سنة ≤ 2 | +4 |
| فرق سنة > 2 | −25 |
| شعبية | `min(popularity / 300, 6)` |
| تقييم | `min(vote_average / 4, 2.5)` |

قواعد القبول:

- `MIN_ACCEPT_SCORE = 55.0`: أقل من ذلك يُعتبر "غير موجود" وليس "فيلم خاطئ".
- **لا يوجد شرط درجة للعبور بين النوعين**: `movie`/`tv` حالتهما الوحيدة هي
  `media_type` الخاصة بالنتيجة؛ النتيجة المخالفة تُرفض بالكامل
  (`TMDBClient.find_match` و`Processor.process_item`) ولا تُقبل "بدرجة أعلى".
  (لا يوجد `CROSS_TYPE_MIN_SCORE` في الكود؛ لا تُضِفه إلى الشرح دون تنفيذه.)
- إن لم تُرجع النتائج شيء مع السنة، تُعاد المحاولة بدون سنة.
- يُختار الأفضل عبر `title` و`original_title` (أو `name`/`original_name` للمسلسلات).

#### 9.3.1 لغة البحث: لغة المستخدم أولاً، ثم الإنجليزية (fallback لا استبدال)

نقطة `/search` في TMDB تطابق الاستعلام مع **العناوين المعروضة** باللغة المطلوبة، لا مع
`original_title` وحده. لذلك العنوان الإنجليزي لعملٍ بلا ترجمة عربية — أفلام آسيوية حديثة مثل
`Humint` أو `Panda Plan` أو `Operation Hadal` — يُرجع **لا نتائج** عند `language=ar`، رغم
وجوده في TMDB.

الحل **fallback لا استبدال**: `TMDBClient._best_candidate` يبحث بلغة المستخدم أولاً، فإن لم
يجد نتيجة مقبولة أعاد البحث بالإنجليزية واعتمد الأعلى درجة:

| الخطوة | السلوك |
|---|---|
| 1 | بحث بلغة المستخدم (`self.language`). إن بلغت الدرجة ≥ `MIN_ACCEPT_SCORE` تُعتمد **دون أي طلب إضافي**. |
| 2 | بحث بالإنجليزية (`FALLBACK_LANGUAGE = "en"`) — يُنفَّذ فقط إذا لم توجد نتيجة مقبولة في الخطوة 1. |
| 3 | فشلت الاثنتان ⇒ `None` (غير موجود). |

| طريقة البحث | 10 عناوين فاشلة سابقاً |
|---|---|
| `language=ar` | **0 / 10** نجحت |
| `language=en` | **10 / 10** (درجات ≈101، أي تطابق تام) |
| بدون بارامتر `language` | **10 / 10** — مطابقة تماماً لـ `en`، لأن TMDB يعيد `en-US` افتراضياً |

**هذا لا يمسّ تفضيل الصور العربية**: اختيار الصورة يتم في `_enrich_images` عبر
`include_image_language={language},en,null`، وهو مستقل تماماً عن لغة البحث.

يُسجَّل اللغة المستخدمة في كل عنصر:

```text
تم اختيار 'Humint' (2026) بدرجة 101.9 [لغة البحث: en]
تعذر البحث بلغة 'ar' لـ 'Humint'؛ نجح البديل بـ 'en'.
```

> لا تُخفِّض `MIN_ACCEPT_SCORE` لتحسين نسبة النجاح؛ عالجه في ورقة "ثقة منخفضة" (§9.3).

### 9.4 اختيار الصور

- يُجلب `/images` فقط عند نقص صورة أو عند تفضيل صور محلية اللغة.
- `include_image_language = "{language},en,null"`.
- الملصق (`posters`): لغة المستخدم أولاً، ثم بلا لغة، ثم الإنجليزية.
- الخلفية (`backdrops`): **بلا نص أولاً**، ثم لغة المستخدم، ثم الإنجليزية.
- الترتيب داخل الفئة: `vote_average` أعلى، ثم عرض أكبر.
- تُستخدم أحجام الصور المختارة في الإعدادات عند بناء رابط الصورة
  (`/t/p/{size}/...`): الافتراضي `w500` للملصق و`w780` للخلفية. الخيار
  `original` يعني الدقة الكاملة، وحجم التنزيل يقارب عشرة أضعاف (5GB لمكتبة
  1000 عنصر بدل ~0.5GB).

### 9.5 الشبكة، retries والتهدئة

- `requests.Session` مشتركة، مع `User-Agent` واضح.
- `timeout=(5, request_timeout)`؛ الافتراضي 20 ثانية للقراءة.
- تهدئة موحّدة (`_throttle`) بقفل وخيط آمن: `min_request_interval` افتراضياً 0.35 ثانية.
- عدد المحاولات `max_retries` (1..10، افتراضي 3):

| الحالة | السلوك |
|---|---|
| `401` | `TMDBAuthError` فوراً (لا إعادة) |
| `404` | إرجاع `{}` (تعامل كعدم وجود) |
| `429` | احترام `Retry-After` (1..30 ثانية) أو `2×attempt`، ثم إعادة |
| `5xx` | backoff: `min(8, 1.5^attempt + jitter)` |
| خطأ شبكة/timeout | backoff وإعادة |
| `4xx` أخرى | `TMDBError` مع رسالة الخادم |
| JSON غير صالح/غير dict | `TMDBError` |

### 9.6 الكاش — `cache.py`

- ملف `tmdb_cache.json` في مجلد البيانات.
- مفتاح الإدخال:
  `match-v2|<kind>|<language>|<prefer_localized>|<normalized title>|<year>`
- TTL بالأيام (`cache_ttl_days`, افتراضي 30).
- سعة قصوى 5000 إدخال؛ تُحذف الأقدم عند التجاوز.
- الحفظ ذري، والملف التالف يُتجاهل مع تحذير.
- `use_cache=False` يعطّل القراءة والكتابة.
- `close()` يستدعي `flush()`؛ لا تنسه.

---

## 10. خط أنابيب الصور — `images.py`

### 10.1 التحويل

`convert_to_jpeg(src, dest, quality)`:

- جودة مقيدة بين 60 و100.
- يقرأ أول إطار للصور المتحركة، ويطبّق `ImageOps.exif_transpose`.
- `_flatten_to_rgb`: RGBA/LA/P بشفافية → خلفية بيضاء؛ غير ذلك يُحوَّل إلى RGB.
- حفظ JPEG بـ `optimize=True`, `progressive=True`، و`subsampling`:
  - 0 عند 100،
  - 1 عند ≥ 90،
  - 2 لما دون ذلك.
- كتابة إلى `.<name>.<uuid>.tmp` ثم `os.replace`، وحذف المؤقت في `finally`.

### 10.2 تحويل WebP

- `convert_webp_file`: الهدف الافتراضي نفس الاسم بـ `.jpg`.
  - إن وُجد الهدف و`overwrite=False` → `None` (تخطٍّ، دون حذف المصدر).
  - بعد نجاح التحويل يُحذف المصدر؛ فشل الحذف يُسجَّل تحذيراً فقط.
- `convert_webp_in_folder`:
  - غير متكرر افتراضياً؛ المتكرر يُستخدم للمسلسلات عند `convert_nested_webp=True`.
  - يتجاهل المجلدات المخفية/`@eaDir`/سلة المحذوفات.
  - `dry_run` يعدّ ما كان سيُحوَّل في `would_convert` دون كتابة؛ ويبقى `converted` صفراً
    لأن المعاينة لا تُنفّذ شيئاً.
  - يجمع `ConversionResult(converted, skipped, failed)`.

### 10.3 التنزيل

`ImageService.save_image(url, folder, names, overwrite)`:

1. إذا كان `names[0]` غير موجود أو `overwrite=True` → تنزيله.
2. إن كان موجوداً → لا تنزيل.
3. لكل اسم إضافي (مثل `background.jpg`) → نسخ ذري من الأساسي إن كان ناقصاً أو مسموح الاستبدال.
4. يعيد قائمة المسارات المكتوبة فعلاً.

`_download_to`:

- محاولتان فقط لكل صورة.
- رفض ما ليس `image/*` أو `application/octet-stream`.
- حد أقصى 80MB (ترويسة `Content-Length` وأثناء البث).
- فحص الإلغاء لكل chunk.
- ملف مؤقت `.part` ثم `_finalize_download`:
  - JPEG + RGB/L + غير متحرك → `verify()` ثم نقل بايتات كما هي.
  - خلاف ذلك → إعادة ترميز JPEG بالجودة المطلوبة.
- أي فشل → `ImageError` مع تنظيف المؤقت.

**إعادة المحاولة تُحدث فقط لأخطاء الشبكة**: `requests.RequestException` (ومنها `Timeout`) تعيد
المحاولة مرة واحدة؛ أما `OSError` (صلاحيات/قرص) و`ImageError` (نوع محتوى/حجم) فلا تُعاد
المحاولة أبداً — أرخص وأوضح من تنزيل الصورة مرتين لسبب غير عابر.

### 10.4 النسخ

`copy_image` يستخدم `shutil.copy2` إلى ملف مؤقت ثم `os.replace`، ويعيد `False` إذا كان الهدف
موجوداً و`overwrite=False`.

---

## 11. المنسّق — `processor.py`

### 11.1 ترتيب `process_item`

0. **فحص قابلية الكتابة** لمجلد العمل (`images.is_folder_writable`). يتم **مرة واحدة قبل أي
   طلب شبكة**: إن كان المجلد غير قابل للكتابة فلا بحث في TMDB ولا تنزيل إطلاقاً، والنتيجة
   `ERROR` مع `target_writable=False` ورسالة `مجلد الهدف غير قابل للكتابة: <path>`.
   **يُستثنى وضع المعاينة**: `dry_run` لا يكتب شيئاً، ومجلد الإخراج الفرعي غير موجود إلا في
   التشغيل الحقيقي، ففحصه هناك يجعل كل عنصر `ERROR` زائفاً.
   > `os.access(folder, os.W_OK)` **غير موثوق على ويندوز**: يُرجع `True` لمجلدات مرفوضة
   > الصلاحية ومشاركات القراءة فقط. الفحص الصحيح هو إنشاء ملف مُسقِط مؤقت وحذفه.
   > مع `output_root` يتم الفحص على مجلد الإخراج لا على المصدر، فتختفي حالة
   > «المشاركة قراءة فقط» (انظر 11.3).
1. **تحويل WebP** حسب الإعدادات (متكرر للمسلسلات فقط عند التفعيل).
2. إن كان `convert_only` → `_conversion_only_result` وانتهى.
3. تحديد الأنواع: `want_poster`/`want_fanart`/`want_background` من `download_*`، ثم `need_*` لكل نوع على حدة.
4. فحص وجود كل نوع فعلياً (ملف موجود وحجمه > 0)؛ وجود `poster.jpg` لا يُسقط `fanart.jpg`.
5. إن كانت الأنواع الثلاثة معطّلة → `SKIPPED` بلا شبكة.
6. إن لم يبقَ أي نوع ناقص → `SKIPPED` (مع ذكر التحويلات إن حدثت).
7. إن لم يكن هناك `client` → `MediaArtError`.
8. `find_match` → إن لم يوجد → `NOT_FOUND`.
9. إن لم يوجد رابط لأي نوع مطلوب → `SKIPPED` مع تحذير (لا `ERROR`).
10. `dry_run` → `PREVIEW` (معاينة) مع خطة التنزيل، دون كتابة.
11. تنزيل الملصق والخلفية: طلب واحد للخلفية ثم نسخ من نفس البيانات للأسماء المطلوبة.
12. إنشاء `folder.jpg` إن مُفعّل.
13. الحالة النهائية وفق الجدول أدناه.

### 11.2 جدول الحالة النهائية

| الشرط | الحالة |
|---|---|
| مجلد الهدف غير قابل للكتابة | `ERROR` (مع `target_writable=False`) |
| كل الصور المطلوبة موجودة بعد العملية، ولا أخطاء | `OK` |
| كل المطلوب موجود لكن نوع مطلوب بلا رابط في TMDB | `PARTIAL` |
| تعذّر بعض المطلوب لكن توفّرت صورة واحدة على الأقل | `PARTIAL` |
| لا صورة مطلوبة توفّرت (فشل كل التنزيلات) | `ERROR` |
| كل الأنواع معطّلة (`download_*` = false) | `SKIPPED` |
| الصور المطلوبة موجودة مسبقاً | `SKIPPED` |
| وضع المعاينة (`dry_run`) | `PREVIEW` (معاينة) — لا تنفيذ ولا كتابة |
| لا مطابقة في TMDB | `NOT_FOUND` |
| إلغاء المستخدم | `CANCELLED` |

`ItemResult` يحمل: `status`, `message`, `matched_title`, `poster_saved`, `backdrop_saved`,
`webp_converted`, `dry_run`.

### 11.3 `output_root` و manifest (B2/P13)

عند ضبط `output_root` (من حقل «مجلد إخراج الصور» في الواجهة، أو `--output-root` في CLI،
أو `config.json` مباشرة) تنتقل كل الكتابة من
مجلد العمل إلى شجرة موازية:

| العنصر | بلا `output_root` | مع `output_root` |
|---|---|---|
| مسار الكتابة | `item.path` | `output_root / item.path.relative_to(library_path)` |
| فحص الكتابة | مجلد العمل | مجلد الإخراج |
| `poster.jpg` / `fanart.jpg` / `background.jpg` / `folder.jpg` | في المصدر | في شجرة الإخراج |
| تحويل WebP داخل المصدر | يعمل | يُعطَّل (يكتب بجوار المصدر) |
| `.mediaart_manifest.json` | لا يوجد | يُحدَّث بعد كل عنصر |

قواعد أساسية (`_target_dir`, `app/services/processor.py`):

- المسار النسبي يُحسب من `library_path`؛ عنصر خارج الجذر يُكتب في مكانه الأصلي مع تحذير
  (كما في المواصفة)، فلا يُفقد شيء بصمت.
- `output_root == library_path` ⇒ يُتجاهل تماماً (سلوك كأن الخيار غير مضبوط، بلا manifest).
- `AppConfig.output_root` نوعه **`str`** لا `Path`: الإعدادات تُسلسَل بـ`asdict` ثم
  `json.dumps`، و`Path` غير قابل للتسلسل. التحقق في `ensure_output_root()` (إنشاء +
  ملف فحص) ويُطلق `ValueError` برسالة عربية.
- `from_dict` تُسقط `output_root` غير القابل للكتابة (مشاركة غير متصلة) بدل إفشال الإعداد
  كله — نفس مبدأ «إعداد تالف لا يمنع الإقلاع».

**manifest** (`app/services/manifest.py`):

```json
{"version": 1,
 "entries": {"Inception (2010)": {
    "files": ["background.jpg", "fanart.jpg", "poster.jpg"],
    "ts": "2026-11-12T14:02:11+00:00",
    "status": "ok"}}}
```

- الكتابة ذرّية (`mkstemp` + `os.replace`)، وتحدث **بعد كل عنصر** — إغلاق مفاجئ لا يُفقد
  العمل المكتمل.
- `update_entry` يُرجع `changed=False` إن تطابقت الملفات والحالة ⇒ لا كتابة ولا تغيير في
  `ts`، فيبقى الملف مطابقاً بايتاً ببايت عند إعادة التشغيل على شجرة مكتملة.
- الحالة تُشتق من `ItemResult.status`: `ERROR` ⇒ `error`، `PARTIAL` ⇒ `partial`، وإلا
  `ok` إن وُجدت ملفات؛ و`PREVIEW`/`NOT_FOUND`/`CANCELLED` لا تُسجَّل.
- ملفات موجودة في شجرة الإخراج بلا مدخل في manifest ⇒ تحذير «تخطّي: الملف موجود مسبقاً
  بلا سجل» (لا استبدال تلقائي).

### 11.4 الملخص

`RunSummary` يحسب `ok`, `partial`, `succeeded`, `skipped`, `not_found`, `errors`,
`cancelled_count`, `preview`، ويجمع `webp_converted` و`webp_would_convert`. `summary_text()`
بالعربية ويُستخدم في GUI وCLI. قسم «معاينة» يظهر في الملخص فقط إذا وُجدت عناصر معروضة.

---

### 11.5 التوازي والإلغاء (B1/P9)

- `AppConfig.max_workers` (1–8، افتراضي 3). `1` يعني المسار التسلسلي القديم حرفياً.
- `Processor.run` يوزّع العناصر على `ThreadPoolExecutor`، ثم ينتظر الـfutures
  **بترتيب الإرسال**: النتائج وإشارات الواجهة تظهر بترتيب المكتبة دائماً.
- كل مهمة معزولة في `_process_isolated`: استثناء عنصر واحد يصبح `ERROR` لذلك
  العنصر فقط ولا يوقف البقية.
- التهدئة مشتركة داخل `TMDBClient` (`_throttle_lock` يلفّ النوم وتحديث
  `_last_request`)، فعدة خيوط لا تتجاوز المعدل.
- `OutputManifest` يستخدم `RLock` حول `update_entry`/`flush`/`entry`. الـflush يبقى
  بعد كل عنصر: كلفته `fsync` لملف صغير أمام ثانية شبكة، وإبقاؤه يحفظ وعد
  «لا تفقد عملاً مكتملاً عند إغلاق مفاجئ».
- الإلغاء تعاوني: `scanner.discover_media(should_cancel=...)` يتوقف بين المجلدات،
  و`images.convert_webp_in_folder(should_cancel=...)` بين الملفات ويعيد
  `ConversionResult.cancelled`. الـCLI يحوّل SIGINT إلى `Event` (رمز 130)،
  والواجهة تمرّر `QThread.requestInterruption` عبر `RunWorker._should_cancel`.

### 11.6 أنواع الصور المستقلة (A-types)

- ثلاثة مفاتيح: `download_poster` (افتراضي `True`)، `download_fanart` و`download_background`
  (افتراضيًا `False`). `--images` في CLI يتجاوزها.
- `want_*` تُشتق من المفاتيح، و`need_*` تُفحص **لكل نوع** على حدة: وجود `poster.jpg`
  لا يعني تخطّي `fanart.jpg`، وإعادة التشغيل بإعدادات مختلفة تُكمل الناقص فقط.
- الخلفية تُنزَّل طلباً واحداً إلى أول اسم مطلوب ثم تُنسخ من **نفس البيانات** للأسماء
  الأخرى (`ImageService.save_image`). إذا احتيج `background.jpg` وحده يُنزَّل من الشبكة
  بدل النسخ من `fanart.jpg`.
- لا حذف أبداً عند تعطيل نوع: الملفات القديمة تبقى (آمن للترحيل).
- غياب رابط في TMDB ⇒ تحذير + `SKIPPED`/`PARTIAL`، لا `ERROR`.
- `_mirror_backdrops` حُذفت؛ لا مسار يخلق `background.jpg` قبل معرفة الطلب.

## 12. الواجهة الرسومية — `ui/`

### 12.1 البنية

- `MainWindow` يبني: الترويسة، بطاقة الإعدادات، بطاقة التقدم/الإحصاءات، ثم `QSplitter` عمودي
  يحتوي السجل الحي وجدول النتائج، ثم التذييل.
- الاتجاه RTL، خط `Segoe UI`، ثيم داكن في `theme.py`، وأيقونة مرسومة برمجياً.
- شريط عنوان داكن على Windows عبر `DwmSetWindowAttribute(20)`؛ تجميلي وفشله مسموح.
- سحب وإفلات مجلد يملأ حقل المسار.
- نقر مزدوج على صف نتيجة يفتح مجلد العمل.
- أزرار: دليل الاستخدام، فتح مجلد البيانات، فتح صفحة مفاتيح TMDB.

### 12.2 الإعدادات

- `AppConfig` يُحفظ في `config.json` عبر `save_config` الذري.
- `QSettings("MediaArt", "AutoSync")` يحفظ **فقط** `geometry` و`splitter`، وليس الإعدادات.
- يُحفظ الإعداد عند بدء التشغيل وعند الإغلاق.
- `convert_only` يعطّل حقول التوكن واختبار الاتصال.
- حقل «مجلد إخراج الصور» (`output_edit`) يمرّر `output_root` إلى `AppConfig`: `_sync_config_from_ui`
  يتحقق عبر `ensure_output_root` ولا يحفظ مساراً غير قابل للكتابة (يصبح `""`)، و`_start`
  يعرض رسالة الخطأ ويعود قبل بدء التشغيل.

### 12.3 الخيوط والإشارات

`RunWorker(QThread)`:

| الإشارة | الحمولة | المستهلك |
|---|---|---|
| `progress(int done, int total, str title)` | تقدم | شريط التقدم + الحالة |
| `item_done(object ItemResult)` | نتيجة عنصر | صف في الجدول + العدادات |
| `finished_ok(object RunSummary)` | ملخص | إنهاء الحالة والتقدم |
| `failed(str)` | رسالة صديقة | `QMessageBox.critical` |

- `isInterruptionRequested` يُمرَّر كـ `should_cancel` إلى `Processor` وكـ `cancel_check` إلى
  `ImageService`، لذا يتوقف التنزيل خلال 256KB.
- زر الإيقاف لا يقتل الخيط؛ يطلب الإلغاء وينتظر إنهاء العملية الحالية.
- عند الإغلاق أثناء التشغيل: تأكيد المستخدم، `requestInterruption`، `wait(8000)`، ثم
  `terminate()` كملاذ أخير.

`PingWorker`: عميل مؤقت، `test_connection`, ثم `result(bool, str)`.

`QtLogHandler`:

- `logging.Handler` يبث `(levelname, message)` عبر `LogEmitter` (QObject).
- يُضاف إلى `logging.getLogger("mediaart")` ويُزال عند الإغلاق.
- الواجهة تهرب النص بـ `html.escape` قبل إضافته إلى `QTextEdit`.
- `document().setMaximumBlockCount(4000)` يمنع تضخم الذاكرة.

---

## 13. الإعدادات — `AppConfig`

الملف: `%LOCALAPPDATA%\MediaArtAutoSync\config.json` (أو `MEDIAART_DATA_DIR`).
التحميل يتجاهل المفاتيح المجهولة ويحوّل الأنواع، والملف التالف يعيد القيم الافتراضية.

| المفتاح | النوع | الافتراضي | المدى/القيم | الأثر |
|---|---|---|---|---|
| `tmdb_api_key` | str | `""` | v3 أو v4 | يُستخدم إن لم يوجد متغير بيئة |
| `library_path` | str | `""` | مسار | جذر المكتبة |
| `output_root` | str | `""` | مسار قابل للكتابة | مجلد إخراج بديل للصور (انظر 11.3) |
| `language` | str | `"ar"` | `ar,en,fr,de,es,tr,ja,ko` | لغة البحث والصور |
| `poster_size` | str | `"w500"` | `w185,w342,w500,w780,original` | دقة الملصق المطلوب من TMDB |
| `backdrop_size` | str | `"w780"` | `w300,w780,w1280,original` | دقة الخلفية المطلوبة |
| `jpeg_quality` | int | `95` | 60..100 | جودة إعادة الترميز |
| `overwrite_images` | bool | `False` | — | استبدال الصور وحذف WebP رغم وجود JPG |
| `download_poster` | bool | `True` | — | تنزيل `poster.jpg` |
| `download_fanart` | bool | `False` | — | تنزيل `fanart.jpg` |
| `download_background` | bool | `False` | — | تنزيل `background.jpg` من بيانات الخلفية |
| `create_folder_thumbnail` | bool | `False` | — | نسخة `folder.jpg` (من config/CLI فقط) |
| `convert_existing_webp` | bool | `True` | — | تحويل WebP داخل مجلد العمل |
| `convert_nested_webp` | bool | `False` | — | يشمل مواسم المسلسلات |
| `prefer_localized_artwork` | bool | `False` | — | تفضيل صور لغة المستخدم (يرفع الطلبات ~50%) |
| `dry_run` | bool | `False` | — | بحث فقط بلا كتابة |
| `convert_only` | bool | `False` | — | بلا TMDB |
| `media_filter` | str | `"all"` | `all,movies,series` | تصفية الاكتشاف |
| `request_timeout` | int | `20` | 5..120 | مهلة قراءة الشبكة |
| `min_request_interval` | float | `0.35` | 0..5 | تهدئة بين طلبات TMDB |
| `max_retries` | int | `3` | 1..10 | محاولات TMDB |
| `use_cache` | bool | `True` | — | كاش البحث |
| `cache_ttl_days` | int | `30` | 1..3650 | صلاحية الكاش |
| `negative_cache_ttl_days` | int | `30` | 1..365 | صلاحية كاش «غير موجود» (خطأ خارج المدى يوقف الإقلاع) |
| `max_workers` | int | `3` | 1..8 | عدد مهام العناصر المتوازية |

ملاحظة: `create_folder_thumbnail` غير معروض في الواجهة حالياً؛ يُضبط من `config.json` أو
`AppConfig` في الكود. لا تفترض وجود مفتاح في الواجهة.

---

## 14. السجلات والأسرار

- Logger أساسي: `mediaart`، وأبناء مثل `mediaart.tmdb`, `mediaart.processor`.
- الملف: `app_log.txt`، تدوير عند 3MB، 3 نسخ احتياطية، UTF-8، ومستوى DEBUG دائماً.
- الطرفية: مستوى INFO افتراضياً (DEBUG مع `--verbose`).
- `setup_logging` يعمل مرة واحدة لكل عملية (`_configured`).
- `RedactionFilter` يستبدل:
  - `api_key=...` → `api_key=***`
  - `Bearer ...` → `Bearer ***`
  - `?token=...` / `&token=...` → `token=***`
- لا تُسجّل التوكن أو جسم الاستجابة الكامل أو مسارات المستخدم الحساسة أكثر من اللازم.

---

## 15. سطر الأوامر — `cli.py`

```bat
run.bat --cli --path "D:\Media\Library"
run.bat --cli --path "D:\Media\Library" --dry-run
run.bat --cli --path "D:\Media\Library" --convert-only
run.bat --cli --path "D:\Media\Library" --media series --limit 5 --verbose
run.bat --cli --path "D:\Media\Library" --overwrite --quality 100
```

- `--cli` مخفي من المساعدة لكنه يُفعّل الوضع.
- `main()` يوجّه إلى CLI عند وجود `--cli` أو `--help` أو `--version`.
- الخيارات تُدمج فوق `AppConfig` المحمّل؛ لا تُحفظ تلقائياً بعد التشغيل.
- `--overwrite` و`--localized-artwork` يفرضان "التشغيل" فقط (لا يمكن إطفاء المحفوظ منهما).
- `--dry-run` و`--convert-only` ثلاثية الحالة: غيابهما ⇒ يبقى الإعداد المحفوظ من الواجهة،
  ووجودهما ⇒ يفرضان الوضع لهذه الجلسة.
- `--no-cache` يعطّل الكاش لهذه الجلسة.
- إن فشل إنشاء `Processor` (مجلد إخراج اختفى) يُعاد رمز `2` (إعداد غير صالح) برسالة، لا استثناء غير متوقع.

أكواد الخروج:

| الكود | المعنى |
|---|---|
| 0 | نجاح بلا أخطاء عناصر |
| 1 | حدثت أخطاء أثناء المعالجة أو استثناء غير متوقع |
| 2 | مسار غير صالح أو توكن مفقود |
| 130 | إلغاء بـ Ctrl+C |

---

## 16. الاختبارات

```bat
.venv\Scripts\python.exe -m pytest -q
```

**العدد الحالي: 230 اختباراً ناجحاً** (`pytest -q`، بعد احتساب حالات الـparametrization).
التوزيع الموضوعي:

| الملف | يغطي |
|---|---|
| `test_config.py` | الحفظ/التحميل، الحدود، الملف التالف، الكاش وTTL، فشل الكتابة |
| `test_title_cleaner.py` | الأمثلة، العربية، السنة، التطبيع، مصطلحات الإصدار الملتبسة |
| `test_scanner.py` | الأفلام/المسلسلات، الفلاتر، الموسم المرفوض، المكتبة المسطحة، `Specials` |
| `test_tmdb.py` | التقييم، السنة، اللغات، الصور/الأحجام، الكاش السلبي، المطابقة السالبة |
| `test_images.py` | التحويل، الحذف، التخطي، dry-run، PNG |
| `test_processor.py` | التنزيل الكامل، التخطي، not found، dry-run + output_root، partial، الملخص |
| `test_manifest.py` | إصدار السجل، الوضع للقراءة فقط، الحفظ الذرّي |
| `test_concurrency.py` | التوازي، ترتيب النتائج، عزل الفشل، قفل manifest |
| `test_cancellation.py` | إيقاف الفحص/التحويل، SIGINT ⇒ 130 |
| `test_cli.py` | رموز الخروج، الخيارات، `output_root`، أولوية الأوضاع |
| `test_logging.py` | تنقيح الأسرار، عتبة Qt handler |
| `test_ui_*.py` | عدّادات الواجهة، الإعدادات، إشارات العامل |

مبادئ الاختبارات:

- **بلا شبكة حقيقية وبلا مفتاح**: `test_processor.py` يشغّل `ThreadingHTTPServer` محلياً.
- **بلا كتابة خارج المجلد المؤقت**: `tmp_path` في كل اختبار.
- **سلوك لا تنفيذ**: لا اختبارات هشة على نصوص الواجهة أو تنسيق QSS.
- عند إضافة سلوك جديد، أضف اختباراً في الوحدة المسؤولة، وليس في الواجهة، إلا إذا كان السلوك
  مرئياً فعلاً (مثل ربط إشارة).

اختبار واجهة سريع يدوياً:

```bat
set QT_QPA_PLATFORM=offscreen
.venv\Scripts\python.exe -c "from PyQt6.QtWidgets import QApplication; app=QApplication([]); from app.ui.main_window import MainWindow; w=MainWindow(); print('OK', w.windowTitle())"
```

---

## 17. وصفات التوسعة

### 17.1 مصطلح إصدار جديد

`title_cleaner._TAG_TERMS` + اختبار. لا تعدّل `_TAG_RE` يدوياً.

### 17.2 لغة جديدة

1. أضف `(code, native_name)` إلى `SUPPORTED_LANGUAGES` في `config.py`.
2. إن كانت اللغة RTL، تأكد من تعامل Qt معها (التطبيق مضبوط RTL عموماً).
3. أضف حالة عربية/لاتينية إلى اختبارات التطبيع إن كانت فيها حروف خاصة.

### 17.3 خيار جديد في الواجهة

1. أضف الحقل إلى `AppConfig` مع افتراضي و`__post_init__` عند الحاجة.
2. أضف `chip`/`combo` في `main_window._build_settings_card`.
3. اربطه في `_restore_state` و`_sync_config_from_ui`.
4. أضفه إلى `_set_running` إن كان يجب تعطيله أثناء التشغيل.
5. أضف اختباراً في `test_config.py` للتحميل/الحفظ.

### 17.4 مزوّد بيانات بديل

أنشئ صنفاً بنفس واجهة `TMDBClient`:

```python
find_match(item: MediaItem) -> TMDBMatch | None
close() -> None
```

ثم مرّره إلى `Processor(config, client=...)`. لا تعدّل `Processor` ليعرف مزوّداً بعينه.

### 17.5 صيغة صور جديدة

أضف التحويل داخل `_finalize_download` أو وسّع `convert_to_jpeg`. حافظ على:
التحقق قبل النشر، الكتابة الذرية، وتسطيح الشفافية على الأبيض.

---

## 18. التغليف وبناء الإصدار (PyInstaller + Inno Setup)

### 18.1 خط البناء

```bat
REM 1) الملف التنفيذي الوحيد (بوابة pytest + تنظيف dist + تسمية بإصدار)
build.bat

REM 2) النسخة المحمولة: مجلد + zip + SHA256SUMS.txt
build_release.bat

REM 3) معالج التثبيت Next -> Next -> Finish
installer\build_installer.bat
```

- `build.bat` يبني **ملفاً واحداً** (`BUILD_MODE=gui`)، واسمه يأتي من
  `app\config.py` (المصدر الوحيد لرقم الإصدار): `dist\MediaArtAutoSync-v<VER>.exe`.
  الوضع `--cli` **مدمج داخله**، ولا يوجد إصدار CLI منفصل.
- `build_release.bat` يستدعي `build.bat` (لا يكرّر منطقه)، ثم يتحقق من تطابق
  SHA256 بين الـexe المبني والنسخة داخل `dist\portable\...`، ثم يضغط الحزمة.
- `installer\build_installer.bat` يستدعي `ISCC.exe` على `installer\mediaart.iss`،
  ومخرجُه `installer\Output\MediaArtAutoSync-Setup-<VER>.exe`.
- **كلٌّ من الثلاثة يشغّل `pytest -q` كبوابة** قبل أن يبني (الاختبارات لا تحتاج
  مفتاح TMDB ولا إنترنت).
- المتطلبات: PyInstaller (`pip install pyinstaller`) وInno Setup 6.

### 18.2 المخرجات

| المخرج | المسار |
|---|---|
| الملف التنفيذي | `dist\MediaArtAutoSync-v<VER>.exe` |
| النسخة المحمولة | `dist\portable\MediaArtAutoSync-v<VER>\` (يحتوي `MediaArtAutoSync-v<VER>-portable.exe` + `README.md`) + `dist\MediaArtAutoSync-v<VER>-portable.zip` |
| بصمات SHA256 | `dist\SHA256SUMS.txt` |
| معالج التثبيت | `installer\Output\MediaArtAutoSync-Setup-<VER>.exe` |

### 18.3 قياس الحجم (نتائج فعلية)

| البناء | الحجم (بايت) |
|---|---|
| قبل التحسين | `45,430,602` |
| بعد التحسين (A+B) | `29,004,755` |
| البناء المنشور | `29,002,110` |
| حزمة Portable | `28,705,742` |
| معالج التثبيت | `30,722,854` |

**التوفير: `45,430,602` ← `29,004,755` (−36.15%)**، من:
- `optimize=2` في `Analysis` (إزالة `docstrings` و`assert` من الـbytecode المجمّع).
- حذف 97 ملف ترجمة Qt (بقي `qtbase_ar.qm` و`qtbase_en.qm` فقط): التطبيق لا
  يثبّت `QTranslator` إطلاقاً، وكل نصوصه في الكود.
- استبعاد ملفات لا يحمّلها التطبيق: `opengl32sw.dll` (بديل OpenGL البرمجي)،
  `Qt6Network.dll`، `Qt6Svg.dll`، وثمانية إضافات Qt غير مستخدمة.
- استبعاد `PIL._avif` (7.9 MB) ومساعدي ICC/PDF: التطبيق يقرأ `.webp` ويكتب `.jpg` فقط.

**قرارات مرفوضة بعد القياس:**
- `strip=True`: بلا فائدة على Windows (لا توجد أداة `strip`، فيصبح تحذيراً لكل ملف
  بلا أي توفير).
- `UPX`: وفّر `2,944,984` بايت فقط، مقابل **‎+20.7 MB ذاكرة** وقت التشغيل
  (‎121.2 MB ← ‎141.94 MB، لأن المكتبات المضغوطة تُفكّ في الذاكرة عند التحميل)
  وخطر تحذير SmartScreen. القرار: بلا UPX.

### 18.4 قيود التغليف المعروفة

1. **البناء غير قابل لإعادة الإنتاج بايتاً**: كل بناء يُنتج SHA256 مختلفاً لنفس
   المصدر (قياسات من ثلاثة بنينج متتالية: `29,004,591` / `29,004,755` / `29,002,110`).
   عند النشر استخدم **بصمة البناء المنشور** لا بصمة سابقة.
2. **`--cli` داخل الملف التنفيذي لا يطبع شيئاً**: البناء بـ`console=False`، فالمخرجات
   لا تجد طرفية. رمز الخروج صحيح (`0`/`1`/`2`/`130`). القيد مقبول في 1.0.1؛ الحل
   المستقبلي: `onedir` مع نسخة `console` اختيارية أو `AttachConsole`.
3. **لا توقيع رقمي**: يُظهر Windows تحذير SmartScreen. الاختبار النهائي على جهاز
   نظيف (تثبيت ← تشغيل ← إلغاء تثبيت) **ما زال مطلوباً** ولم يُنفَّذ بعد.
4. `README.md` مضمَّن داخل الحزمة (`datas` في الـspec)، وزر «دليل الاستخدام»
   يقرؤه من `sys._MEIPASS` في وضع `--onefile`.
5. مجلد البيانات يبقى في `%LOCALAPPDATA%` ولا يُحزم داخل الملف التنفيذي.
6. الإصدارات الفعلية للمكتبات في بيئة الاختبار: PyQt6 `6.12.0`، Pillow `13.0.0`،
   requests `2.34.2`، PyInstaller `6.22.3`، Inno Setup `6.7.3`، Python `3.14.7`.

---

## 19. القيود المعروفة

1. **مكتبة مسطحة غير مدعومة** (ملفات فيديو مباشرة في مجلد الفئة).
2. **لا صور على مستوى الموسم/الحلقة**؛ المسلسل يُعالج مرة واحدة.
3. **اختيار مجلد موسم مباشرة مرفوض**؛ اختر الأب.
4. **لا إعادة تسمية** للملفات أو المجلدات، ولا قراءة/كتابة `.nfo`.
5. **جذر واحد لكل تشغيل**؛ لا قائمة مهام لعدة مكتبات.
6. **توازٍ محدود على مستوى العناصر** (`max_workers` 1–8) مع ترتيب نتائج ثابت. طلبات
   TMDB تبقى متسلسلة عملياً: التهدئة تُنفَّذ داخل قفل واحد، فالمكسب يأتي من التنزيل
   والعمل المحلي لا من تزايد عدد الطلبات في الثانية.
7. **الواجهة عربية فقط**؛ البيانات والصور متعددة اللغات.
8. **تلميع Windows فقط**: شريط العنوان الداكن وملفات `.bat`. النواة تعمل على Linux/macOS.
9. **لا توقيع رقمي ولا تحديث تلقائي** بعد؛ المعالج موجود (Inno Setup 6، تثبيت لكل مستخدم في `{localappdata}`).
10. **الكاش JSON بسيط**؛ ليس قاعدة بيانات، ولا يخزّن الصور.
11. **المفتاح المحفوظ في `config.json` نص عادي**؛ للأجهزة المشتركة استخدم متغير بيئة.
12. **`folder.jpg` بلا واجهة**، من الإعدادات فقط.

---

## 20. قائمة مراجعة قبل أي تغيير

- [ ] هل التغيير في الطبقة الصحيحة (core وليس UI)؟
- [ ] هل يحافظ على الثوابت في القسم 6؟
- [ ] هل أضفت/حدّثت اختباراً؟
- [ ] هل `pytest -q` يمر بالكامل (230+ اختباراً)؟
- [ ] هل جرّبت وضع `--convert-only` دون إنترنت؟
- [ ] هل جرّبت الواجهة بـ `QT_QPA_PLATFORM=offscreen`؟
- [ ] هل حدّثت `README.md` للمستخدم و`docs/PLAN.md` إن تغيّر النطاق؟
- [ ] هل نظّفت `config.json`/`tmdb_cache.json`/`app_log.txt` من بيانات الاختبار؟
- [ ] هل راجعت أن التوكن لا يظهر في السجل؟

---

## 21. مصطلحات سريعة

| المصطلح | المعنى |
|---|---|
| `MediaItem` | هدف واحد: مجلد فيلم أو جذر مسلسل |
| `TMDBMatch` | نتيجة مطابقة من TMDB مع مسارات الصور |
| `ItemResult` | نتيجة معالجة عنصر واحد |
| `RunSummary` | تجميع نتائج تشغيل كامل |
| `AppConfig` | كل إعدادات المستخدم |
| `RedactionFilter` | حجب الأسرار من السجلات |
| `QtLogHandler` | جسر السجل إلى الواجهة |
| ثقب `background.jpg` | نوع مستقل: يُنزَّل من الشبكة إن طُلب وحده، لا نسخة من `fanart.jpg` |
| المكتبة المسطحة | فيديوهات مباشرة دون مجلد لكل عمل |
