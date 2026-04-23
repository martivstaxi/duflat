"""Static configuration for CS Reviews — app IDs, country lists, thresholds."""

APP_CONFIG = {
    'name': 'BiliBili',
    'android_package': 'tv.danmaku.bili',
    'ios_id': '736536022',  # bilibili — "All Your Fav Videos" (bundle id tv.danmaku.bilianime)
}

# Country-state knobs — adjust here.
INACTIVE_THRESHOLD = 3   # consecutive empty polls → country marked inactive
DISCOVERY_DAYS = 30      # force a full re-scan of every country this often

# Scope rule: Mainland China excluded across all platforms. HK, TW, MO in scope.
EXCLUDED_COUNTRIES = {'cn'}

APPLE_COUNTRIES = [
    'us', 'gb', 'ca', 'au', 'nz', 'ie',
    'de', 'fr', 'it', 'es', 'nl', 'be', 'ch', 'at', 'se', 'no', 'dk', 'fi',
    'pl', 'cz', 'sk', 'hu', 'ro', 'bg', 'hr', 'si', 'rs', 'gr', 'pt',
    'lt', 'lv', 'ee', 'is', 'mt', 'lu', 'cy', 'md',
    'hk', 'mo', 'tw', 'jp', 'kr',
    'sg', 'my', 'id', 'ph', 'th', 'vn',
    'in', 'pk', 'bd', 'lk', 'np',
    'ru', 'ua', 'by', 'kz', 'uz', 'az', 'am', 'ge', 'kg', 'tj', 'tm',
    'tr', 'il', 'sa', 'ae', 'qa', 'kw', 'bh', 'om', 'jo', 'lb', 'eg',
    'za', 'ng', 'ke', 'gh', 'tz', 'ug', 'zw', 'ci', 'sn', 'cm',
    'dz', 'ma', 'tn',
    'br', 'mx', 'ar', 'cl', 'co', 'pe', 'uy', 'py', 'bo', 've', 'ec',
    'cr', 'pa', 'gt', 'sv', 'hn', 'ni', 'do',
]

# Google Play — country → primary UI language (hl, gl).
GPLAY_COUNTRIES = {
    'us': 'en', 'gb': 'en', 'ca': 'en', 'au': 'en', 'nz': 'en', 'ie': 'en',
    'de': 'de', 'at': 'de', 'ch': 'de',
    'fr': 'fr', 'be': 'fr', 'lu': 'fr',
    'it': 'it',
    'es': 'es', 'mx': 'es', 'ar': 'es', 'co': 'es', 'cl': 'es', 'pe': 'es',
    'uy': 'es', 've': 'es', 'ec': 'es', 'cr': 'es', 'pa': 'es', 'gt': 'es',
    'nl': 'nl',
    'se': 'sv', 'no': 'no', 'dk': 'da', 'fi': 'fi',
    'pl': 'pl', 'cz': 'cs', 'sk': 'sk', 'hu': 'hu', 'ro': 'ro', 'bg': 'bg',
    'hr': 'hr', 'si': 'sl', 'rs': 'sr', 'gr': 'el',
    'pt': 'pt', 'br': 'pt',
    'lt': 'lt', 'lv': 'lv', 'ee': 'et',
    'hk': 'zh-HK', 'mo': 'zh-HK', 'tw': 'zh-TW', 'sg': 'en',
    'jp': 'ja', 'kr': 'ko',
    'my': 'ms', 'id': 'id', 'ph': 'en', 'th': 'th', 'vn': 'vi',
    'in': 'en', 'pk': 'en', 'bd': 'bn', 'lk': 'si', 'np': 'ne',
    'ru': 'ru', 'ua': 'uk', 'by': 'ru', 'kz': 'ru', 'uz': 'uz',
    'tr': 'tr',
    'il': 'he', 'sa': 'ar', 'ae': 'ar', 'qa': 'ar', 'kw': 'ar',
    'bh': 'ar', 'om': 'ar', 'jo': 'ar', 'lb': 'ar',
    'eg': 'ar', 'ma': 'ar', 'dz': 'ar', 'tn': 'ar',
    'za': 'en', 'ng': 'en', 'ke': 'en', 'gh': 'en',
}
