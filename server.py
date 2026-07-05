#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DroidMarket — Play Market 2014 Style
MultiVersion Android APK Store
+ OldMarket (Android 1.6) Compatibility Layer
+ ULTIMATE DDoS PROTECTION
"""

import os
import io
import json
import time
import zipfile
import hashlib
import sys
import re
import secrets
import asyncio
from aiohttp import web
from aiohttp.web import middleware
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from PIL import Image
import multiprocessing
import gc

# Monkey-patch aiohttp resume_writing AssertionError
import aiohttp.base_protocol
_resume_writing_orig = aiohttp.base_protocol.BaseProtocol.resume_writing
def _safe_resume_writing(self):
    try:
        _resume_writing_orig(self)
    except AssertionError:
        pass
aiohttp.base_protocol.BaseProtocol.resume_writing = _safe_resume_writing

# Monkey-patch aiohttp web_protocol to suppress BadHttpMessage tracebacks
import aiohttp.web_protocol
_orig_data_received = aiohttp.web_protocol.RequestHandler.data_received
def _safe_data_received(self, data):
    try:
        _orig_data_received(self, data)
    except aiohttp.http_exceptions.BadHttpMessage as e:
        self.log.warning(f"Bad request: {e}")
        self.transport.close()
aiohttp.web_protocol.RequestHandler.data_received = _safe_data_received

# === ЛОГИ (ПОДРОБНЫЕ) ===
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger("droidmarket")
log.setLevel(logging.DEBUG)

# Включаем access-логи aiohttp
for name in ['aiohttp', 'aiohttp.access']:
    logging.getLogger(name).setLevel(logging.INFO)
logging.getLogger('asyncio').setLevel(logging.WARNING)

# === ПУТИ ===
BASE_DIR = Path(__file__).parent.resolve()
APKS_DIR = BASE_DIR / "apks"
STATIC_DIR = BASE_DIR / "static"
ICONS_DIR = STATIC_DIR / "icons"
DATA_FILE = BASE_DIR / "apps_data.json"
CONFIG_FILE = BASE_DIR / "config.json"
USERS_FILE = BASE_DIR / "users.json"
LOGO_FILE = BASE_DIR / "icon.jpg"
BLOCKLIST_FILE = BASE_DIR / "blocklist.json"

# === КОНСТАНТЫ ===
SITE_NAME = "DroidMarket"
ICON_SIZE = (128, 128)
SCAN_INTERVAL = 60
SESSION_LIFETIME = 86400
MAX_REQUESTS_PER_IP = 120    # за 10 секунд
BAN_DURATION = 300          # 5 минут первичный бан
BAN_DURATION_HARD = 3600    # 1 час для повторных нарушителей
CLEANUP_INTERVAL = 30
MAX_CONCURRENT_PER_IP = 8   # макс одновременных запросов с одного IP
MAX_BODY_SIZE = 1024 * 10   # макс тело запроса (10KB) для не-API
BURST_THRESHOLD = 20        # порог для burst-детекции (за 1 секунду)
BACKLOG_SIZE = 4096         # размер TCP-очереди (чтобы не терять соединения)

# Whitelist IP-адресов (прокси, CDN, мониторинг)
TRUSTED_PROXIES = set()  # заполняется из config.json или вручную

# Белый список IP — пропускаются без проверок
IP_WHITELIST = {'91.78.23.106'}

# Чёрный список User-Agent (полное совпадение содержит)
UA_BLACKLIST = [
    'go-http-client',          # DDoS-инструмент
    'genomecrawlerd',          # агрессивный сканер
    'libredtail-http',         # эксплойт-сканер
    'python-httpx',            # MCP/API-сканер
    'python-requests',
    'masscan', 'nmap', 'zmap',
    'sqlmap', 'nikto', 'wpscan',
    'curl', 'wget',
    'mj12bot', 'semrushbot',
    'java/', 'okhttp',
]
_UA_CHECK_CACHE = {}

def is_bad_ua(ua):
    ua_lower = (ua or '').lower()
    if ua_lower in _UA_CHECK_CACHE:
        return _UA_CHECK_CACHE[ua_lower]
    result = any(p in ua_lower for p in UA_BLACKLIST)
    if len(_UA_CHECK_CACHE) < 2000:
        _UA_CHECK_CACHE[ua_lower] = result
    return result

# Боты-сканеры AI
AI_BOT_PATTERNS = [
    'gptbot', 'claude', 'google-extended', 'ccbot', 'anthropic',
    'cohere', 'bytespider', 'applebot-extended',
    'perplexity', 'omgili', 'imagesift', 'magpie',
    'meta-externalagent', 'ai2bot', 'diffbot', 'dataforseo',
]
_AI_CACHE = {}
def is_ai_bot(ua):
    ua_lower = (ua or '').lower()
    if ua_lower in _AI_CACHE:
        return _AI_CACHE[ua_lower]
    result = any(p in ua_lower for p in AI_BOT_PATTERNS)
    if len(_AI_CACHE) < 1000:
        _AI_CACHE[ua_lower] = result
    return result

# Список path'ей с повышенным лимитом (почти безлимит) — статика, progress
HIGH_LIMIT_PATHS = ('/static/', '/api/progress', '/api/client/', '/icon.jpg', '/logo.png')

# Разные лимиты для разных типов путей
RATE_LIMITS = {
    'high':    {'max': 600,  'window': 10},   # статика, progress
    'normal':  {'max': 120,  'window': 10},   # страницы
    'api':     {'max': 60,   'window': 10},   # /api/ (кроме exempt)
    'download':{'max': 30,   'window': 30},   # /download/
}

# Лимит для прокси-режима (все запросы через приватный IP)
PROXY_GLOBAL_LIMIT = 3000  # запросов в 10 секунд

# Опасные последовательности в пути (path traversal, shell injection)
DANGEROUS_PATH_PATTERNS = [
    '/..',  '/%2e', '/%252e', 'cgi-bin', 'bin/', 'bash',
    'cmd.exe', 'powershell', 'wget ', 'curl ',
]

def get_rate_limit_for_path(path):
    if path.startswith('/download/'):
        return RATE_LIMITS['download']
    if path.startswith('/api/'):
        return RATE_LIMITS['api']
    if any(path.startswith(p) for p in HIGH_LIMIT_PATHS):
        return RATE_LIMITS['high']
    return RATE_LIMITS['normal']

def load_blocklist():
    try:
        if BLOCKLIST_FILE.exists():
            with open(BLOCKLIST_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {'banned_ips': {}, 'suspicious_ips': {}}

def save_blocklist(data):
    try:
        with open(BLOCKLIST_FILE, 'w') as f:
            json.dump(data, f, separators=(',', ':'))
    except:
        pass

class DDoSShield:
    """Многоуровневая защита от DDoS (ядерная v3 — прокси-aware)"""

    def __init__(self):
        self.ip_requests = defaultdict(list)
        self.global_requests = []  # для прокси-режима (кумулятивный лимит)
        self.banned_ips = {}
        self.suspicious_ips = {}
        self.concurrent_ips = defaultdict(int)
        self.violation_count = {}
        self.stats = {'total_requests': 0, 'blocked_requests': 0, 'concurrent_blocked': 0}
        self._lock = asyncio.Lock()

        # Загружаем персистентный blocklist (но чистим приватные IP — они от прокси)
        bl = load_blocklist()
        now = time.time()
        for ip, until in bl.get('banned_ips', {}).items():
            if until > now and not self._is_private_ip(ip):
                self.banned_ips[ip] = until
        for ip, data in bl.get('suspicious_ips', {}).items():
            if not self._is_private_ip(ip):
                self.suspicious_ips[ip] = data

    def _persist(self):
        """Сохраняет активные баны на диск"""
        data = {'banned_ips': {ip: until for ip, until in self.banned_ips.items()},
                'suspicious_ips': {ip: data for ip, data in self.suspicious_ips.items()}}
        save_blocklist(data)

    async def cleanup_loop(self):
        while True:
            await asyncio.sleep(CLEANUP_INTERVAL)
            try:
                now = time.time()
                changed = False
                async with self._lock:
                    for ip in list(self.ip_requests.keys()):
                        self.ip_requests[ip] = [t for t in self.ip_requests[ip] if t > now - 15]
                        if not self.ip_requests[ip]:
                            del self.ip_requests[ip]
                    for ip in list(self.banned_ips.keys()):
                        if self.banned_ips[ip] < now:
                            del self.banned_ips[ip]
                            changed = True
                    for ip in list(self.suspicious_ips.keys()):
                        if now - self.suspicious_ips[ip][1] > 300:
                            del self.suspicious_ips[ip]
                            changed = True
                    for ip in list(self.violation_count.keys()):
                        if now - self.violation_count[ip][1] > 86400:
                            del self.violation_count[ip]
                if changed:
                    self._persist()
            except Exception:
                pass

    def _get_ip(self, request):
        real_ip = request.headers.get('X-Real-IP')
        if real_ip:
            return real_ip.strip()
        forwarded = request.headers.get('X-Forwarded-For')
        if forwarded:
            ips = [ip.strip() for ip in forwarded.split(',')]
            if TRUSTED_PROXIES:
                for ip in reversed(ips):
                    if ip not in TRUSTED_PROXIES:
                        return ip
            return ips[0]
        cf_ip = request.headers.get('CF-Connecting-IP')
        if cf_ip:
            return cf_ip.strip()
        return request.remote or '0.0.0.0'

    @staticmethod
    def _is_private_ip(ip):
        """Проверяет, является ли IP локальным/приватным (прокси-режим)"""
        if ip in ('127.0.0.1', '::1', '0.0.0.0'):
            return True
        if ip.startswith('192.168.') or ip.startswith('10.'):
            return True
        if ip.startswith('172.') and len(ip) > 5:
            try:
                second = int(ip.split('.')[1])
                if 16 <= second <= 31:
                    return True
            except:
                pass
        return False

    def _ban(self, ip, duration, now):
        """Банит IP и сохраняет на диск (не банит приватные IP — это прокси)"""
        if self._is_private_ip(ip):
            return
        self.banned_ips[ip] = now + duration
        self._persist()

    def _flag_suspicious(self, ip, now):
        if self._is_private_ip(ip):
            return
        if ip in self.suspicious_ips:
            self.suspicious_ips[ip][0] += 1
            self.suspicious_ips[ip][1] = now
        else:
            self.suspicious_ips[ip] = [1, now]

    async def check(self, request):
        ip = self._get_ip(request)
        now = time.time()
        self.stats['total_requests'] += 1

        if ip in IP_WHITELIST:
            return None

        ua = request.headers.get('User-Agent', '')
        if ua.startswith('DroidMarket'):
            return None

        path = request.path

        # === 0. Блокировка известных плохих UA ===
        if is_bad_ua(ua):
            self.stats['blocked_requests'] += 1
            self._ban(ip, BAN_DURATION_HARD, now)
            return web.Response(status=403, text="Forbidden\n", headers={'Connection': 'close'})

        # === 0.5. AI-боты — блокируем полностью ===
        if is_ai_bot(ua):
            self.stats['blocked_requests'] += 1
            return web.Response(status=403, text="Forbidden\n", headers={'Connection': 'close'})

        # === 1. Бан-лист ===
        if ip in self.banned_ips:
            if self.banned_ips[ip] > now:
                self.stats['blocked_requests'] += 1
                return web.Response(status=503, text="503 Service Unavailable\n",
                                    headers={'Retry-After': str(int(self.banned_ips[ip] - now)),
                                             'Connection': 'close'})
            else:
                del self.banned_ips[ip]

        # === 2. Path traversal / shell injection в пути ===
        path_lower = path.lower()
        for pat in DANGEROUS_PATH_PATTERNS:
            if pat in path_lower:
                self._flag_suspicious(ip, now)
                vc = self.violation_count.get(ip, [0, now])
                vc[0] += 5
                vc[1] = now
                self.violation_count[ip] = vc
                self._ban(ip, BAN_DURATION_HARD, now)
                self.stats['blocked_requests'] += 1
                return web.Response(status=403, text="Forbidden\n", headers={'Connection': 'close'})

        # === 3. Пустой/короткий User-Agent (сканеры) ===
        if not ua or len(ua) < 8:
            sc = self.suspicious_ips.get(ip, [0, now])
            if sc[0] > 2:
                self._ban(ip, BAN_DURATION, now)
                self.stats['blocked_requests'] += 1
                return web.Response(status=418, text="418 I'm a Teapot\n",
                                    headers={'Connection': 'close'})
            self._flag_suspicious(ip, now)

        # === 4. Опасные пути (сканирование уязвимостей) ===
        dangerous_paths = [
            '/wp-admin', '/phpmyadmin', '/.env', '/.git', '/cgi-bin',
            '/shell', '/cmd', '/exec', '/adminer', '/mysql', '/wp-login',
            '/xmlrpc.php', '/actuator', '/console', '/backup', '/dump',
            '/info.php', '/test.php', '/admin.php', '/config.php',
            '/debug', '/dev', '/log', '/logs', '/trace', '/status',
            '/metrics', '/healthz', '/health', '/jenkins', '/grafana',
            '/prometheus', '/kibana', '/swagger', '/api/swagger',
            '/api/v1/', '/api/v2/', '/api/docs',
            '/vendor/', '/composer.json', '/package.json',
            '/server-status', '/server-info',
        ]
        if any(path.startswith(p) for p in dangerous_paths):
            vc = self.violation_count.get(ip, [0, now])
            vc[0] += 3
            vc[1] = now
            self.violation_count[ip] = vc
            self._ban(ip, BAN_DURATION_HARD, now)
            self.stats['blocked_requests'] += 1
            return web.Response(status=418, text="418 I'm a Teapot\n",
                                headers={'Connection': 'close'})

        # === 4.5. Статика и служебные пути — без rate-limit ===
        if path.startswith('/static/') or path in ('/icon.jpg', '/logo.png', '/robots.txt', '/sitemap.xml',
                                                    '/api/progress', '/api/client/latest', '/api/client/analytics',
                                                    '/api/avatars'):
            return None

        # === 4.6. Прокси-режим (приватный IP) — кумулятивный лимит ===
        # Все юзеры идут через один IP прокси, поэтому per-IP лимит сломает всех.
        # Используем общий лимит для всех запросов с приватных IP.
        if self._is_private_ip(ip):
            async with self._lock:
                self.global_requests.append(now)
                self.global_requests = [t for t in self.global_requests if t > now - 10]
                if len(self.global_requests) > PROXY_GLOBAL_LIMIT:
                    self.stats['blocked_requests'] += 1
                    return web.Response(status=429, text="Too Many Requests\n",
                                        headers={'Connection': 'close'})
            return None

        # === 5. Rate-limit (скользящее окно, зависит от типа пути) ===
        rl = get_rate_limit_for_path(path)
        window = rl['window']
        limit = rl['max']

        async with self._lock:
            # Concurrent limit check
            cur = self.concurrent_ips[ip]
            if cur >= MAX_CONCURRENT_PER_IP:
                self.stats['concurrent_blocked'] += 1
                return web.Response(status=429, text="Too Many Concurrent Requests\n",
                                    headers={'Connection': 'close'})
            self.concurrent_ips[ip] = cur + 1

            self.ip_requests[ip].append(now)
            self.ip_requests[ip] = [t for t in self.ip_requests[ip] if t > now - window]
            cnt = len(self.ip_requests[ip])

        if cnt > limit:
            vc = self.violation_count.get(ip, [0, now])
            vc[0] += 1
            vc[1] = now
            self.violation_count[ip] = vc
            ban_for = BAN_DURATION_HARD if vc[0] > 1 else BAN_DURATION
            self._ban(ip, ban_for, now)
            self.stats['blocked_requests'] += 1
            return web.Response(status=429, text="Too Many Requests\n",
                                headers={'Retry-After': str(ban_for),
                                         'Connection': 'close'})

        return None

    async def dec(self, request):
        async with self._lock:
            ip = self._get_ip(request)
            self.concurrent_ips[ip] = max(0, self.concurrent_ips[ip] - 1)

# === ГЛОБАЛЬНЫЕ ОБЪЕКТЫ ===
ddos_shield = DDoSShield()
apps_data = {}
users_data = {}
admin_sessions = {}
scan_progress = {'status': 'idle', 'total': 0, 'current': 0, 'message': ''}
data_lock = asyncio.Lock()
scan_lock = asyncio.Lock()

# Буфер счётчика загрузок (batch-save)
_download_buffer = defaultdict(int)
_download_buffer_lock = asyncio.Lock()

async def send_file(request, path, content_type):
    """Stream a file reliably, avoids FileResponse sendfile bugs on Windows."""
    path = Path(path)
    if not path.is_file():
        raise web.HTTPNotFound()
    size = path.stat().st_size
    resp = web.StreamResponse()
    resp.content_type = content_type
    resp.content_length = size
    resp.headers['Accept-Ranges'] = 'bytes'
    await resp.prepare(request)
    with open(str(path), 'rb') as f:
        chunk = f.read(65536)
        while chunk:
            await resp.write(chunk)
            chunk = f.read(65536)
    return resp

# === ЯДЕРНЫЙ MIDDLEWARE ===
@middleware
async def ddos_middleware(request, handler):
    check = await ddos_shield.check(request)
    if check:
        return check
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception as e:
        log.error(f"Handler error: {e}")
        return web.Response(status=500, text="500 Internal Server Error\n")
    finally:
        await ddos_shield.dec(request)

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def hash_pw_salted(p):
    salt = secrets.token_hex(8)
    return salt + "$" + hashlib.sha256((salt + p).encode()).hexdigest()

def check_pw_salted(p, stored):
    parts = stored.split("$", 1)
    if len(parts) != 2:
        return hashlib.sha256(p.encode()).hexdigest() == stored
    return hashlib.sha256((parts[0] + p).encode()).hexdigest() == parts[1]

def fmt_size(b):
    for u in ['B', 'KB', 'MB', 'GB']:
        if b < 1024.0:
            return f"{b:.1f} {u}"
        b /= 1024.0
    return f"{b:.1f} TB"

def api_to_android(api_level):
    api_map = {
        1: '1.0+', 2: '1.1+', 3: '1.5+', 4: '1.6+', 5: '2.0+', 6: '2.0.1+', 7: '2.1+', 8: '2.2+',
        9: '2.3.0+', 10: '2.3.3+', 11: '3.0+', 12: '3.1+', 13: '3.2+', 14: '4.0.1+', 15: '4.0.3+',
        16: '4.1+', 17: '4.2+', 18: '4.3+', 19: '4.4+', 20: '4.4W', 21: '5.0+', 22: '5.1+',
        23: '6.0+', 24: '7.0+', 25: '7.1+', 26: '8.0+', 27: '8.1+', 28: '9.0+', 29: '10+',
        30: '11+', 31: '12+', 32: '12L+', 33: '13+', 34: '14+', 35: '15+'
    }
    try:
        level = int(api_level)
        return api_map.get(level, f'API {level}')
    except:
        return api_level

def safe_icon_name(pkg_name):
    safe = re.sub(r'[^\w\-.]', '_', pkg_name)[:100]
    return safe if safe else 'default'

async def compress_icon(data, pkg_name):
    try:
        img = Image.open(io.BytesIO(data))
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        img = img.resize(ICON_SIZE, Image.Resampling.LANCZOS)
        safe_name = safe_icon_name(pkg_name)
        icon_path = ICONS_DIR / f"{safe_name}.png"
        img.save(icon_path, 'PNG', optimize=True, compress_level=9)
        return f"{safe_name}.png"
    except Exception:
        return 'default_icon.png'

async def extract_icon_from_apk(fp, pkg_name):
    try:
        from androguard.core.apk import APK as AndroAPK
        apk = AndroAPK(fp)
        res = apk.get_android_resources()
        manifest = apk.get_android_manifest_xml()
        app = manifest.find('application')
        icon_ref = None
        if app is not None:
            for attr_name, attr_val in app.attrib.items():
                if 'icon' in attr_name.lower():
                    icon_ref = attr_val
                    break
        if icon_ref and icon_ref.startswith('@'):
            res_id = int(icon_ref[1:], 16)
            configs = res.get_resolved_res_configs(res_id)
            png_candidates = []
            for config, file_name in configs:
                if file_name.lower().endswith(('.png', '.webp')):
                    dpi = config.get_density()
                    png_candidates.append((dpi, file_name))
            png_candidates.sort(key=lambda x: -x[0])
            for dpi, file_name in png_candidates:
                try:
                    data = apk.zip.read(file_name)
                    if len(data) > 500:
                        result = await compress_icon(data, pkg_name)
                        if result and result != 'default_icon.png':
                            return result
                except:
                    continue
    except:
        pass
    
    # Fallback
    try:
        with zipfile.ZipFile(fp, 'r') as zf:
            all_files = zf.namelist()
            for name in all_files:
                if 'icon' in name.lower() and name.endswith(('.png', '.jpg', '.webp')):
                    if '.9.png' in name:
                        continue
                    try:
                        data = zf.read(name)
                        if len(data) > 500:
                            result = await compress_icon(data, pkg_name)
                            if result and result != 'default_icon.png':
                                return result
                    except:
                        continue
    except:
        pass
    
    return 'default_icon.png'

def generate_fallback_icon(pkg_name, name=''):
    try:
        h = hashlib.md5((pkg_name + name).encode()).digest()
        r, g, b = h[0] | 64, h[1] | 64, h[2] | 64
        img = Image.new('RGBA', ICON_SIZE, (r, g, b, 255))
        from PIL import ImageDraw, ImageFont
        draw = ImageDraw.Draw(img)
        text = (name or pkg_name)[:2].upper()
        try:
            font = ImageFont.truetype("arial.ttf", 48)
        except:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (ICON_SIZE[0] - tw) / 2 - bbox[0]
        y = (ICON_SIZE[1] - th) / 2 - bbox[1]
        draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)
        safe_name = safe_icon_name(pkg_name)
        icon_path = ICONS_DIR / f"{safe_name}.png"
        img.save(icon_path, 'PNG', optimize=True, compress_level=9)
        return f"{safe_name}.png"
    except:
        return 'default_icon.png'

async def parse_apk(fp, ftype='apk'):
    fp = Path(fp)
    if not fp.exists():
        return None
    try:
        from androguard.core.apk import APK
        apk = APK(str(fp))
        if apk.is_valid_APK():
            pkg = apk.get_package() or 'unknown'
            ver = apk.get_androidversion_name() or '?'
            sdk = str(apk.get_min_sdk_version() or '?')
            android_ver = api_to_android(sdk)
            name = apk.get_app_name()
            if not name or name == pkg or len(name) < 2:
                try:
                    name = apk.get_element('application', 'android:label')
                except:
                    pass
            if not name or name == pkg:
                name = pkg
            return {
                'package': pkg, 'name': name, 'version': ver, 'min_sdk': sdk,
                'android_ver': android_ver, 'filename': fp.name,
                'size': fp.stat().st_size, 'size_formatted': fmt_size(fp.stat().st_size),
                'mtime': fp.stat().st_mtime, 'added_date': datetime.now().strftime("%Y-%m-%d %H:%M"),
                'type': ftype, 'downloads': 0
            }
    except:
        pass
    
    # Fallback через zipfile
    try:
        with zipfile.ZipFile(fp, 'r') as zf:
            if 'AndroidManifest.xml' in zf.namelist():
                txt = zf.read('AndroidManifest.xml').decode('utf-8', errors='ignore')
                m = re.search(r'package="([^"]+)"', txt)
                pkg = m.group(1) if m else fp.stem
                return {
                    'package': pkg, 'name': fp.stem.replace('_', ' ').replace('-', ' '),
                    'version': '?', 'min_sdk': '?', 'android_ver': '?', 'filename': fp.name,
                    'size': fp.stat().st_size, 'size_formatted': fmt_size(fp.stat().st_size),
                    'mtime': fp.stat().st_mtime, 'added_date': datetime.now().strftime("%Y-%m-%d %H:%M"),
                    'type': ftype, 'downloads': 0
                }
    except:
        pass
    
    return {
        'package': fp.stem, 'name': fp.stem.replace('_', ' ').replace('-', ' '),
        'version': '?', 'min_sdk': '?', 'android_ver': '?', 'filename': fp.name,
        'size': fp.stat().st_size, 'size_formatted': fmt_size(fp.stat().st_size),
        'mtime': fp.stat().st_mtime, 'added_date': datetime.now().strftime("%Y-%m-%d %H:%M"),
        'type': ftype, 'downloads': 0
    }

async def scan_file(fp):
    fp = Path(fp)
    ext = fp.suffix.lower()
    try:
        if ext == '.apk':
            return await parse_apk(fp, 'apk')
        elif ext == '.xapk':
            return await parse_archive(fp, 'xapk')
        elif ext in ('.apks', '.apkm'):
            return await parse_archive(fp, ext[1:])
    except Exception:
        pass
    return None

async def parse_archive(fp, ftype):
    fp = Path(fp)
    try:
        with zipfile.ZipFile(fp, 'r') as zf:
            apks = [f for f in zf.namelist() if f.endswith('.apk')]
            if not apks:
                return None
            base = next((f for f in apks if 'base.apk' in f.lower()), apks[0])
            tmp = fp.with_suffix('.temp.apk')
            with open(tmp, 'wb') as f:
                f.write(zf.read(base))
            r = await parse_apk(str(tmp), ftype)
            try:
                tmp.unlink()
            except:
                pass
            if r:
                r['filename'] = fp.name
                return r
    except:
        pass
    return None

# === ЗАГРУЗКА ДАННЫХ ===
def load_data():
    global apps_data, users_data
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            for key, value in loaded.items():
                if 'versions' not in value:
                    apps_data[key] = {
                        'name': value.get('name', key),
                        'icon': value.get('icon', 'default_icon.png'),
                        'versions': [{
                            'filename': value.get('filename'),
                            'version': value.get('version', '?'),
                            'android_ver': value.get('android_ver', '?'),
                            'min_sdk': value.get('min_sdk', '?'),
                            'size': value.get('size', 0),
                            'size_formatted': value.get('size_formatted', '0 B'),
                            'mtime': value.get('mtime', 0),
                            'added_date': value.get('added_date', datetime.now().strftime("%Y-%m-%d %H:%M")),
                            'type': value.get('type', 'apk'),
                            'downloads': value.get('downloads', 0)
                        }]
                    }
                else:
                    apps_data[key] = value
        except Exception as e:
            log.error(f"Error loading data: {e}")
    
    if USERS_FILE.exists():
        try:
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                users_data.update(json.load(f))
        except:
            pass

def save_data():
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(apps_data, f, ensure_ascii=False, separators=(',', ':'))
    except Exception as e:
        log.error(f"Save error: {e}")

def init_dirs():
    for d in (APKS_DIR, STATIC_DIR, ICONS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    if not LOGO_FILE.exists():
        try:
            img = Image.new("RGBA", (96, 96), (148, 171, 58, 255))
            img.save(LOGO_FILE, "PNG")
        except:
            pass
    if not (ICONS_DIR / "default_icon.png").exists():
        try:
            img = Image.new("RGBA", (128, 128), (80, 80, 80, 255))
            img.save(ICONS_DIR / "default_icon.png", "PNG", optimize=True)
        except:
            pass

def init_config():
    global TRUSTED_PROXIES, SITE_NAME
    if not CONFIG_FILE.exists():
        pw = secrets.token_hex(6)
        cfg = {
            "admin_password_hash": hash_pw_salted(pw),
            "trusted_proxies": [],
            "_note": "Password shown on first run"
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        print("\n" + "=" * 40)
        print(f"  ADMIN PASSWORD: {pw}")
        print("=" * 40 + "\n")
    else:
        cfg = load_config()
        TRUSTED_PROXIES = set(cfg.get("trusted_proxies", []))
        SITE_NAME = cfg.get("site_name", "DroidMarket")
        if TRUSTED_PROXIES:
            log.warning(f"Trusted proxies: {TRUSTED_PROXIES}")

def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    pw = secrets.token_hex(6)
    cfg = {
        "admin_password_hash": hash_pw_salted(pw),
        "trusted_proxies": []
    }
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except:
        pass
    return cfg

def ensure_app_ids():
    changed = False
    current_ids = {data.get('id') for data in apps_data.values() if data.get('id')}
    next_id = max(current_ids) + 1 if current_ids else 1
    for pkg, data in apps_data.items():
        if 'id' not in data or data['id'] is None:
            while next_id in current_ids:
                next_id += 1
            data['id'] = next_id
            current_ids.add(next_id)
            changed = True
    if changed:
        save_data()

def get_pkg_by_id(app_id):
    for pkg, data in apps_data.items():
        if data.get('id') == app_id:
            return pkg
    return None

# === СКАНИРОВАНИЕ ===
async def scan_apks(force=False):
    global scan_progress
    if not scan_lock.locked():
        async with scan_lock:
            scan_progress['status'] = 'scanning'
            scan_progress['message'] = 'Collecting files...'
            
            files = {}
            for ext in ('*.apk', '*.xapk', '*.apks', '*.apkm'):
                for p in APKS_DIR.glob(ext):
                    if p.is_file():
                        files[p.name] = p
            
            existing_files = set()
            for pkg, data in apps_data.items():
                for v in data['versions']:
                    existing_files.add(v['filename'])
            
            new_files = {}
            for fn, fp in files.items():
                if force or fn not in existing_files:
                    new_files[fn] = fp
            
            if not new_files:
                scan_progress['status'] = 'idle'
                scan_progress['message'] = 'No new files'
                return
            
            total = len(new_files)
            scan_progress['total'] = total
            scan_progress['current'] = 0
            scan_progress['message'] = f'Scanning {total} files...'
            
            new_data = {}
            for i, (fn, fp) in enumerate(new_files.items()):
                scan_progress['current'] = i + 1
                scan_progress['message'] = f'{i+1}/{total}: {fn[:40]}...'
                
                try:
                    r = await scan_file(str(fp))
                    if r:
                        pkg = r['package']
                        icon_name = await extract_icon_from_apk(str(fp), pkg)
                        if icon_name == 'default_icon.png':
                            icon_name = generate_fallback_icon(pkg, r['name'])
                        
                        if pkg not in new_data:
                            if pkg in apps_data:
                                new_data[pkg] = {
                                    'name': apps_data[pkg]['name'],
                                    'icon': apps_data[pkg].get('icon', 'default_icon.png'),
                                    'versions': apps_data[pkg]['versions'].copy()
                                }
                            else:
                                new_data[pkg] = {'name': r['name'], 'icon': icon_name, 'versions': []}
                        else:
                            if new_data[pkg].get('icon') == 'default_icon.png':
                                new_data[pkg]['icon'] = icon_name
                        
                        version_entry = {
                            'filename': r['filename'], 'version': r['version'],
                            'android_ver': r['android_ver'], 'min_sdk': r['min_sdk'],
                            'size': r['size'], 'size_formatted': r['size_formatted'],
                            'mtime': r['mtime'], 'added_date': r['added_date'],
                            'type': r['type'], 'downloads': r.get('downloads', 0)
                        }
                        
                        exists = any(v['filename'] == r['filename'] for v in new_data[pkg]['versions'])
                        if not exists:
                            new_data[pkg]['versions'].append(version_entry)
                            new_data[pkg]['versions'].sort(key=lambda x: x.get('mtime', 0), reverse=True)
                except Exception as e:
                    log.error(f"Error scanning {fn}: {e}")
            
            for pkg, data in new_data.items():
                if pkg in apps_data:
                    existing_versions = {v['filename']: v for v in apps_data[pkg]['versions']}
                    for v in data['versions']:
                        if v['filename'] not in existing_versions:
                            apps_data[pkg]['versions'].append(v)
                    apps_data[pkg]['versions'].sort(key=lambda x: x.get('mtime', 0), reverse=True)
                    if apps_data[pkg].get('icon') == 'default_icon.png':
                        apps_data[pkg]['icon'] = data['icon']
                else:
                    apps_data[pkg] = data
            
            save_data()
            scan_progress['status'] = 'idle'
            scan_progress['message'] = f'Done: {len(new_files)} files scanned'

async def bg_scan():
    await asyncio.sleep(10)
    while True:
        try:
            await scan_apks()
        except Exception as e:
            log.error(f"Scanner: {e}")
        await asyncio.sleep(SCAN_INTERVAL)

async def bg_flush_downloads():
    """Сброс буфера загрузок в файл раз в 30 секунд"""
    await asyncio.sleep(30)
    while True:
        try:
            async with _download_buffer_lock:
                if _download_buffer:
                    for key, count in _download_buffer.items():
                        pkg, version = key
                        if pkg in apps_data:
                            for v in apps_data[pkg]['versions']:
                                if v['version'] == version:
                                    v['downloads'] = v.get('downloads', 0) + count
                                    break
                    _download_buffer.clear()
                    save_data()
        except Exception as e:
            log.error(f"Flush downloads error: {e}")
        await asyncio.sleep(30)

# === МЕТА-ТЕГ ДЛЯ GOOGLE SEARCH CONSOLE ===
FAVICON = '<link rel="icon" href="/favicon.ico" type="image/x-icon" /><link rel="shortcut icon" href="/favicon.ico" type="image/x-icon" />'
GSC_META = FAVICON + '<meta name="google-site-verification" content="z8leaUwMC55lFmqj90O5kjTD2yq-fl_yWFlakYklHPI" />'

# === CSS И ШАБЛОНЫ ===
CSS = r"""
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Droid Sans', 'Segoe UI', Arial, sans-serif; background: linear-gradient(180deg, #1a1a1a 0%, #2d2d2d 50%, #1a1a1a 100%); color: #e0e0e0; min-height: 100vh; }
a { color: #66bbff; text-decoration: none; }
a:hover { text-decoration: underline; }
.header { background: linear-gradient(180deg, #0d47a1 0%, #1565c0 50%, #0d47a1 100%); border-bottom: 2px solid #1a237e; box-shadow: inset 0 1px 0 rgba(255,255,255,0.2), 0 3px 6px rgba(0,0,0,0.6); color: #fff; padding: 0 20px; height: 56px; display: flex; align-items: center; justify-content: space-between; gap: 16px; position: sticky; top: 0; z-index: 100; }
.header-left { display: flex; align-items: center; gap: 10px; }
.header-logo-img { width: 32px; height: 32px; vertical-align: middle; border-radius: 6px; box-shadow: 0 2px 4px rgba(0,0,0,0.4); }
.header-logo { font-size: 24px; font-weight: 700; letter-spacing: -0.5px; text-shadow: 0 -1px 0 rgba(0,0,0,0.5); }
.header-logo span { font-weight: 300; color: #90caf9; }
.header-search { flex: 1; max-width: 480px; }
.header-search form { display: flex; background: linear-gradient(180deg, #1e3a5c 0%, #0d2847 100%); border-radius: 4px; overflow: hidden; border: 1px solid #1a237e; box-shadow: inset 0 1px 3px rgba(0,0,0,0.5), 0 1px 0 rgba(255,255,255,0.1); }
.header-search input { flex: 1; padding: 10px 14px; border: none; font-size: 14px; background: transparent; color: #fff; outline: none; text-shadow: 0 1px 0 rgba(0,0,0,0.3); }
.header-search input::placeholder { color: rgba(255,255,255,0.5); }
.header-search button { padding: 10px 16px; background: linear-gradient(180deg, #2568a8 0%, #184a7a 100%); border: none; border-left: 1px solid #0d2847; cursor: pointer; color: #90caf9; font-size: 16px; box-shadow: inset 0 1px 0 rgba(255,255,255,0.15); }
.header-search button:hover { background: linear-gradient(180deg, #2a75bc 0%, #1d5a92 100%); }
.header-actions { display: flex; gap: 6px; }
.header-actions a { color: #bbdefb; text-decoration: none; font-size: 13px; font-weight: 500; padding: 6px 12px; border-radius: 3px; transition: background 0.15s; background: linear-gradient(180deg, #1565c0 0%, #0d47a1 100%); border: 1px solid #0d2378; box-shadow: inset 0 1px 0 rgba(255,255,255,0.2), 0 1px 2px rgba(0,0,0,0.3); }
.header-actions a:hover { background: linear-gradient(180deg, #1e88e5 0%, #1565c0 100%); text-decoration: none; box-shadow: inset 0 1px 0 rgba(255,255,255,0.25), 0 2px 4px rgba(0,0,0,0.4); }
.topnav { background: linear-gradient(180deg, #37474f 0%, #263238 100%); padding: 0 20px; border-top: 1px solid #455a64; border-bottom: 2px solid #1c282d; box-shadow: 0 2px 4px rgba(0,0,0,0.4); display: flex; gap: 0; position: sticky; top: 56px; z-index: 99; }
.topnav a { color: #b0bec5; text-decoration: none; padding: 0 20px; height: 40px; line-height: 40px; font-size: 13px; font-weight: 500; border-bottom: 2px solid transparent; transition: color 0.15s, border-color 0.15s; text-shadow: 0 -1px 0 rgba(0,0,0,0.5); }
.topnav a:hover { color: #ffffff; text-decoration: none; }
.topnav a.active { color: #64b5f6; border-bottom-color: #1976d2; background: linear-gradient(180deg, #455a64 0%, #37474f 100%); box-shadow: inset 0 1px 0 rgba(255,255,255,0.1); }
.stat-bar { max-width: 1200px; margin: 0 auto; padding: 12px 20px 0; font-size: 13px; color: #90a4ae; text-shadow: 0 1px 0 rgba(0,0,0,0.5); }
.stat-bar b { color: #64b5f6; }
.progress-container { max-width: 1200px; margin: 0 auto; padding: 8px 20px; display: none; }
.progress-container.active { display: block; }
.progress-bar-outer { background: linear-gradient(180deg, #263238 0%, #1c252a 100%); border-radius: 3px; height: 8px; overflow: hidden; border: 1px solid #1c282d; box-shadow: inset 0 2px 4px rgba(0,0,0,0.6); }
.progress-bar-inner { background: linear-gradient(180deg, #66bb6a 0%, #43a047 50%, #2e7d32 100%); height: 100%; width: 0%; transition: width 0.3s ease; border-radius: 2px; box-shadow: inset 0 1px 0 rgba(255,255,255,0.3), 0 1px 2px rgba(0,0,0,0.3); }
.progress-text, .progress-message { font-size: 11px; color: #90a4ae; margin-top: 2px; text-shadow: 0 1px 0 rgba(0,0,0,0.5); }
.sort-bar { max-width: 1200px; margin: 0 auto; padding: 8px 20px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-size: 13px; color: #90a4ae; }
.sort-bar a { color: #cfd8dc; text-decoration: none; padding: 5px 12px; border-radius: 3px; transition: all 0.15s; background: linear-gradient(180deg, #455a64 0%, #37474f 100%); border: 1px solid #263238; box-shadow: inset 0 1px 0 rgba(255,255,255,0.1), 0 1px 2px rgba(0,0,0,0.3); font-size: 12px; }
.sort-bar a:hover { background: linear-gradient(180deg, #546e7a 0%, #455a64 100%); text-decoration: none; box-shadow: inset 0 1px 0 rgba(255,255,255,0.15), 0 2px 4px rgba(0,0,0,0.4); }
.sort-bar a.active { background: linear-gradient(180deg, #1976d2 0%, #0d47a1 100%); color: #ffffff; border-color: #0d2378; box-shadow: inset 0 1px 0 rgba(255,255,255,0.25), 0 1px 2px rgba(0,0,0,0.3); }
.sort-bar .count { margin-left: auto; color: #78909c; font-size: 12px; }
.app-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; padding: 14px 20px; max-width: 1200px; margin: 0 auto; }
.app { background: linear-gradient(180deg, #fafafa 0%, #eeeeee 100%); border-radius: 4px; overflow: hidden; display: flex; padding: 16px; gap: 16px; border: 1px solid #bdbdbd; box-shadow: 0 2px 6px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.8); transition: all 0.2s; }
.app:hover { box-shadow: 0 6px 16px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.9); transform: translateY(-2px); }
.app-icon { flex-shrink: 0; width: 64px; height: 64px; border-radius: 8px; overflow: hidden; background: linear-gradient(180deg, #e0e0e0 0%, #bdbdbd 100%); border: 2px solid #9e9e9e; box-shadow: inset 0 1px 3px rgba(0,0,0,0.3), 0 2px 4px rgba(0,0,0,0.2); }
.app-icon img { width: 100%; height: 100%; object-fit: contain; padding: 4px; }
.app-info { flex: 1; min-width: 0; }
.app-title { font-size: 16px; font-weight: 700; color: #212121; margin-bottom: 4px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; text-shadow: 0 1px 0 rgba(255,255,255,0.8); }
.app-title a { color: #1565c0; text-decoration: none; }
.app-title a:hover { color: #0d47a1; }
.app-meta { font-size: 12px; color: #616161; display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 6px; }
.app-sdk { font-size: 11px; color: #424242; background: linear-gradient(180deg, #f5f5f5 0%, #e0e0e0 100%); padding: 2px 8px; border-radius: 10px; border: 1px solid #bdbdbd; box-shadow: inset 0 1px 0 rgba(255,255,255,0.8); }
.app-dl { font-size: 12px; color: #424242; margin-top: 4px; }
.app-dl b { color: #1976d2; }
.app-actions { margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap; }
.btn-download { display: inline-block; background: linear-gradient(180deg, #4caf50 0%, #388e3c 100%); color: #fff; padding: 6px 16px; font-size: 12px; font-weight: 600; border-radius: 3px; text-decoration: none; transition: all 0.15s; border: 1px solid #2e7d32; box-shadow: inset 0 1px 0 rgba(255,255,255,0.3), 0 1px 2px rgba(0,0,0,0.3); }
.btn-download:hover { background: linear-gradient(180deg, #66bb6a 0%, #43a047 100%); text-decoration: none; box-shadow: inset 0 1px 0 rgba(255,255,255,0.35), 0 2px 4px rgba(0,0,0,0.4); }
.btn-versions { display: inline-block; background: linear-gradient(180deg, #757575 0%, #616161 100%); color: #fff; padding: 6px 16px; font-size: 12px; font-weight: 600; border-radius: 3px; text-decoration: none; transition: all 0.15s; border: 1px solid #424242; box-shadow: inset 0 1px 0 rgba(255,255,255,0.2), 0 1px 2px rgba(0,0,0,0.3); }
.btn-versions:hover { background: linear-gradient(180deg, #9e9e9e 0%, #757575 100%); text-decoration: none; box-shadow: inset 0 1px 0 rgba(255,255,255,0.25), 0 2px 4px rgba(0,0,0,0.4); }
.badge-versions { background: linear-gradient(180deg, #64b5f6 0%, #1976d2 100%); color: #ffffff; font-size: 10px; padding: 2px 8px; border-radius: 10px; font-weight: 700; border: 1px solid #0d47a1; box-shadow: inset 0 1px 0 rgba(255,255,255,0.3), 0 1px 2px rgba(0,0,0,0.2); }
.badge-type { background: linear-gradient(180deg, #ffb74d 0%, #f57c00 100%); color: #ffffff; font-size: 10px; padding: 2px 8px; border-radius: 3px; font-weight: 700; text-transform: uppercase; border: 1px solid #e65100; box-shadow: inset 0 1px 0 rgba(255,255,255,0.3), 0 1px 2px rgba(0,0,0,0.2); }
.detail-page { max-width: 760px; margin: 16px auto; padding: 20px; }
.detail-card { background: linear-gradient(180deg, #fafafa 0%, #eeeeee 100%); border-radius: 4px; border: 1px solid #bdbdbd; overflow: hidden; margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.8); }
.detail-header { display: flex; gap: 20px; padding: 24px; align-items: center; background: linear-gradient(180deg, #f5f5f5 0%, #eeeeee 100%); border-bottom: 2px solid #bdbdbd; }
.detail-icon { flex-shrink: 0; width: 80px; height: 80px; border-radius: 10px; background: linear-gradient(180deg, #e0e0e0 0%, #bdbdbd 100%); border: 3px solid #9e9e9e; overflow: hidden; box-shadow: inset 0 2px 6px rgba(0,0,0,0.3), 0 3px 6px rgba(0,0,0,0.3); }
.detail-icon img { width: 100%; height: 100%; object-fit: contain; padding: 4px; }
.detail-name { flex: 1; }
.detail-name h1 { font-size: 24px; font-weight: 700; color: #212121; margin-bottom: 4px; text-shadow: 0 1px 0 rgba(255,255,255,0.8); }
.detail-name .pkg { font-size: 12px; color: #757575; font-family: 'Consolas', monospace; }
.detail-stats { display: grid; grid-template-columns: repeat(2, 1fr); gap: 0; border-top: 2px solid #bdbdbd; }
.detail-stats div { padding: 16px; text-align: center; border-right: 2px solid #bdbdbd; background: linear-gradient(180deg, #fafafa 0%, #f0f0f0 100%); }
.detail-stats div:last-child { border-right: none; }
.detail-stats b { display: block; font-size: 24px; color: #1976d2; font-weight: 700; text-shadow: 0 1px 0 rgba(255,255,255,0.8); }
.detail-stats span { font-size: 11px; color: #616161; text-transform: uppercase; letter-spacing: 0.5px; }
.detail-download { display: block; background: linear-gradient(180deg, #4caf50 0%, #388e3c 50%, #2e7d32 100%); color: #fff; text-align: center; padding: 16px; font-size: 16px; font-weight: 700; border-radius: 4px; text-decoration: none; margin: 16px 20px; transition: all 0.15s; border: 2px solid #2e7d32; box-shadow: inset 0 1px 0 rgba(255,255,255,0.3), 0 3px 6px rgba(0,0,0,0.4); }
.detail-download:hover { background: linear-gradient(180deg, #66bb6a 0%, #43a047 50%, #388e3c 100%); text-decoration: none; box-shadow: inset 0 1px 0 rgba(255,255,255,0.35), 0 4px 8px rgba(0,0,0,0.5); }
.versions-list { padding: 0 20px 20px; }
.versions-list h3 { font-size: 16px; color: #212121; margin-bottom: 12px; font-weight: 700; text-shadow: 0 1px 0 rgba(255,255,255,0.8); }
.version-item { background: linear-gradient(180deg, #f5f5f5 0%, #eeeeee 100%); border: 1px solid #bdbdbd; border-radius: 3px; padding: 12px 16px; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; transition: all 0.15s; box-shadow: inset 0 1px 0 rgba(255,255,255,0.6), 0 1px 2px rgba(0,0,0,0.15); }
.version-item:hover { background: linear-gradient(180deg, #fafafa 0%, #f5f5f5 100%); box-shadow: inset 0 1px 0 rgba(255,255,255,0.8), 0 2px 4px rgba(0,0,0,0.2); }
.version-item .info { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.version-item .version { font-weight: 700; color: #1976d2; font-size: 14px; }
.version-item .detail { font-size: 12px; color: #616161; }
.version-item .dl-link { color: #fff; font-weight: 600; text-decoration: none; font-size: 13px; padding: 6px 14px; border-radius: 3px; transition: all 0.15s; background: linear-gradient(180deg, #1976d2 0%, #0d47a1 100%); border: 1px solid #0d2378; box-shadow: inset 0 1px 0 rgba(255,255,255,0.25), 0 1px 2px rgba(0,0,0,0.3); }
.version-item .dl-link:hover { background: linear-gradient(180deg, #1e88e5 0%, #1565c0 100%); text-decoration: none; box-shadow: inset 0 1px 0 rgba(255,255,255,0.3), 0 2px 4px rgba(0,0,0,0.4); }
.box { max-width: 420px; margin: 40px auto; background: linear-gradient(180deg, #fafafa 0%, #eeeeee 100%); padding: 32px; border-radius: 4px; border: 2px solid #bdbdbd; box-shadow: 0 4px 12px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.8); }
.box h2 { font-size: 22px; color: #212121; margin-bottom: 24px; text-align: center; font-weight: 700; text-shadow: 0 1px 0 rgba(255,255,255,0.8); }
.form-group { margin-bottom: 18px; }
.form-group label { display: block; font-size: 13px; color: #424242; margin-bottom: 6px; font-weight: 600; }
.form-group input { width: 100%; padding: 12px 16px; border: 2px solid #bdbdbd; border-radius: 3px; font-size: 14px; outline: none; transition: all 0.15s; background: linear-gradient(180deg, #ffffff 0%, #fafafa 100%); box-shadow: inset 0 2px 4px rgba(0,0,0,0.1), 0 1px 0 rgba(255,255,255,0.5); }
.form-group input:focus { border-color: #1976d2; box-shadow: inset 0 2px 4px rgba(0,0,0,0.1), 0 0 0 3px rgba(25,118,210,0.2); }
.btn-green { display: inline-block; background: linear-gradient(180deg, #4caf50 0%, #388e3c 50%, #2e7d32 100%); color: #fff; padding: 12px 28px; font-size: 15px; font-weight: 700; border: none; border-radius: 3px; cursor: pointer; width: 100%; transition: all 0.15s; border: 2px solid #2e7d32; box-shadow: inset 0 1px 0 rgba(255,255,255,0.3), 0 3px 6px rgba(0,0,0,0.4); }
.btn-green:hover { background: linear-gradient(180deg, #66bb6a 0%, #43a047 50%, #388e3c 100%); box-shadow: inset 0 1px 0 rgba(255,255,255,0.35), 0 4px 8px rgba(0,0,0,0.5); }
.btn-red { display: inline-block; background: linear-gradient(180deg, #f44336 0%, #d32f2f 50%, #c62828 100%); color: #fff; padding: 8px 18px; font-size: 13px; font-weight: 700; border: none; border-radius: 3px; cursor: pointer; transition: all 0.15s; border: 2px solid #c62828; box-shadow: inset 0 1px 0 rgba(255,255,255,0.25), 0 2px 4px rgba(0,0,0,0.3); }
.btn-red:hover { background: linear-gradient(180deg, #ef5350 0%, #e53935 50%, #d32f2f 100%); box-shadow: inset 0 1px 0 rgba(255,255,255,0.3), 0 3px 6px rgba(0,0,0,0.4); }
.btn-blue { display: inline-block; background: linear-gradient(180deg, #2196f3 0%, #1976d2 50%, #1565c0 100%); color: #fff; padding: 6px 14px; font-size: 12px; border: none; border-radius: 3px; cursor: pointer; text-decoration: none; transition: all 0.15s; border: 2px solid #0d47a1; box-shadow: inset 0 1px 0 rgba(255,255,255,0.25), 0 2px 4px rgba(0,0,0,0.3); }
.btn-blue:hover { background: linear-gradient(180deg, #42a5f5 0%, #1e88e5 50%, #1976d2 100%); box-shadow: inset 0 1px 0 rgba(255,255,255,0.3), 0 3px 6px rgba(0,0,0,0.4); }
.btn-sm { padding: 4px 12px; font-size: 11px; }
.adm-header { background: linear-gradient(180deg, #c62828 0%, #b71c1c 50%, #b71c1c 100%) !important; border-bottom-color: #7f0000 !important; }
.table-wrap { background: linear-gradient(180deg, #fafafa 0%, #eeeeee 100%); padding: 20px; max-width: 1200px; margin: 12px auto; border-radius: 4px; border: 2px solid #bdbdbd; box-shadow: 0 3px 10px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.8); }
.table-wrap h3 { font-size: 16px; color: #212121; margin-bottom: 14px; font-weight: 700; text-shadow: 0 1px 0 rgba(255,255,255,0.8); }
.table { width: 100%; border-collapse: collapse; font-size: 13px; }
.table th { text-align: left; padding: 12px 14px; background: linear-gradient(180deg, #e0e0e0 0%, #bdbdbd 100%); color: #424242; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid #9e9e9e; text-shadow: 0 1px 0 rgba(255,255,255,0.5); box-shadow: inset 0 1px 0 rgba(255,255,255,0.5); }
.table td { padding: 12px 14px; border-bottom: 1px solid #bdbdbd; vertical-align: middle; background: linear-gradient(180deg, #ffffff 0%, #fafafa 100%); }
.table td img { width: 36px; height: 36px; border-radius: 6px; object-fit: contain; background: linear-gradient(180deg, #e0e0e0 0%, #bdbdbd 100%); padding: 3px; border: 2px solid #9e9e9e; box-shadow: inset 0 1px 2px rgba(0,0,0,0.2); }
.info-page { max-width: 700px; margin: 16px auto; }
.info-card { background: linear-gradient(180deg, #fafafa 0%, #eeeeee 100%); border-radius: 4px; border: 2px solid #bdbdbd; padding: 28px; box-shadow: 0 3px 10px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.8); }
.info-page h2 { font-size: 22px; color: #212121; margin-bottom: 16px; font-weight: 700; text-shadow: 0 1px 0 rgba(255,255,255,0.8); }
.info-page h3 { font-size: 16px; color: #1976d2; margin-bottom: 12px; margin-top: 24px; font-weight: 700; }
.info-page p { margin-bottom: 10px; color: #424242; line-height: 1.6; }
.telegram-link { display: inline-block; background: linear-gradient(180deg, #2196f3 0%, #1976d2 100%); color: #fff; padding: 10px 22px; border-radius: 3px; text-decoration: none; font-weight: 600; transition: all 0.15s; border: 2px solid #0d47a1; box-shadow: inset 0 1px 0 rgba(255,255,255,0.25), 0 2px 4px rgba(0,0,0,0.3); }
.telegram-link:hover { background: linear-gradient(180deg, #42a5f5 0%, #1e88e5 100%); text-decoration: none; box-shadow: inset 0 1px 0 rgba(255,255,255,0.3), 0 3px 6px rgba(0,0,0,0.4); }
.nav-bottom { max-width: 1200px; margin: 20px auto 0; padding: 16px 20px; text-align: center; border-top: 2px solid #bdbdbd; background: linear-gradient(180deg, #f5f5f5 0%, #eeeeee 100%); border-radius: 4px; box-shadow: inset 0 1px 0 rgba(255,255,255,0.8); }
.nav-bottom a { color: #1976d2; text-decoration: none; margin: 0 14px; font-size: 13px; transition: all 0.15s; font-weight: 600; }
.nav-bottom a:hover { color: #0d47a1; text-decoration: underline; }
.footer { background: linear-gradient(180deg, #424242 0%, #212121 100%); color: #bdbdbd; text-align: center; padding: 18px 10px; font-size: 12px; border-top: 2px solid #1a1a1a; box-shadow: inset 0 1px 0 rgba(255,255,255,0.1); }
.footer .team { color: #64b5f6; font-weight: 700; }
.empty-msg { text-align: center; padding: 60px 20px; color: #757575; }
.empty-msg p { margin-bottom: 8px; font-size: 15px; }
.empty-msg code { background: linear-gradient(180deg, #f5f5f5 0%, #e0e0e0 100%); padding: 3px 10px; border-radius: 3px; font-size: 12px; border: 1px solid #bdbdbd; box-shadow: inset 0 1px 2px rgba(0,0,0,0.1); }
.danger-zone { margin-top: 20px; padding: 18px 20px; background: linear-gradient(180deg, #fff3e0 0%, #ffe0b2 100%); border: 2px solid #ff9800; border-radius: 4px; box-shadow: inset 0 1px 0 rgba(255,255,255,0.5), 0 2px 4px rgba(0,0,0,0.15); }
.danger-zone h3 { color: #e65100 !important; font-size: 14px; margin-top: 0 !important; font-weight: 700; }
@media (max-width: 768px) {
  .header { padding: 0 12px; gap: 8px; }
  .header-search { max-width: 100%; }
  .header-actions a { padding: 6px 10px; font-size: 12px; }
  .app-list { grid-template-columns: 1fr; padding: 12px; gap: 12px; }
  .detail-page { padding: 12px; }
  .detail-header { flex-direction: column; text-align: center; }
  .detail-stats { grid-template-columns: repeat(2, 1fr); }
}
"""

HEADER = r"""
<div class="header">
 <div class="header-left"><img class="header-logo-img" src="/icon.jpg" alt=""><div class="header-logo">Droid<span>Market</span></div></div>
  <div class="header-search"><form method="get" action="/"><input type="text" name="q" value="{{ q|default('') }}" placeholder="Search apps..."><button type="submit">⌕</button></form></div>
  <div class="header-actions"><a href="/profile">Profile</a><a href="/admin">Admin</a></div>
 </div>
 <div class="topnav">
 <a href="/" class="{% if not page_title %}active{% endif %}">Apps</a>
 <a href="/games" class="{% if page_title == 'Games' %}active{% endif %}">Games</a>
 <a href="/info">Info</a>
</div>
"""

FOOTER = r"""
<div class="nav-bottom"><a href="/">Apps</a><a href="/games">Games</a><a href="/info">Info</a><a href="/profile">Profile</a><a href="/admin">Admin</a></div>
<div class="footer"><span class="team">DroidMarket</span> &copy; 2026</div>
"""

PROGRESS_BAR = r"""
{% if progress and progress.status == 'scanning' %}
<div class="progress-container active">
 <div class="progress-message">{{ progress.message }}</div>
 <div class="progress-bar-outer"><div class="progress-bar-inner" style="width: {{ (progress.current / progress.total * 100)|round(1) if progress.total > 0 else 0 }}%;"></div></div>
 <div class="progress-text">{{ progress.current }}/{{ progress.total }}</div>
</div>
{% endif %}
"""

MAIN_T = r"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><meta name="description" content="DroidMarket — Android APK Market. Скачать приложения и игры для Android бесплатно. APK, XAPK, APKS."><meta name="keywords" content="android, apk, скачать, приложения, игры, droidmarket, андроид, маркет">""" + GSC_META + r"""<meta property="og:title" content="DroidMarket"><meta property="og:description" content="Android APK store — download apps and games"><meta property="og:type" content="website"><meta property="og:site_name" content="DroidMarket"><meta name="twitter:card" content="summary"><title>DroidMarket</title>
<style>""" + CSS + r"""</style>
<script>function updateProgress(){fetch('/api/progress',{signal:AbortSignal.timeout(2000)}).then(r=>r.json()).then(d=>{var c=document.querySelector('.progress-container');var i=document.querySelector('.progress-bar-inner');var t=document.querySelector('.progress-text');var m=document.querySelector('.progress-message');if(d.status==='scanning'){c.classList.add('active');i.style.width=(d.total>0?(d.current/d.total*100):0)+'%';t.textContent=d.current+'/'+d.total;m.textContent=d.message;}else{c.classList.remove('active');}}).catch(function(){});}setTimeout(function tick(){updateProgress();setTimeout(tick,2000+Math.random()*2000)},2000+Math.random()*2000);</script>
</head><body>
""" + HEADER + r"""
<div class="stat-bar">Apps: <b>{{ total }}</b></div>
<div class="sort-bar"><span>Sort:</span><a href="?sort=name" class="{% if sort_by == 'name' %}active{% endif %}">Name</a><a href="?sort=downloads" class="{% if sort_by == 'downloads' %}active{% endif %}">Popular</a><a href="?sort=newest" class="{% if sort_by == 'newest' %}active{% endif %}">Newest</a>{% if q %}<span class="count">Search: <b>{{ q }}</b></span>{% endif %}</div>
""" + PROGRESS_BAR + r"""
<div class="app-list">
{% if apps %}{% for a in apps %}
 <div class="app">
  <div class="app-icon"><img src="/static/icons/{{ a.icon }}?v={{ loop.index }}" onerror="this.src='/static/icons/default_icon.png'" alt="{{ a.name }}"></div>
  <div class="app-info">
   <div class="app-title"><a href="/app/{{ a.package }}">{{ a.name }}</a>{% if a.versions_count > 0 %}<span class="badge-versions">{{ a.versions_count }}v</span>{% endif %}{% if a.type and a.type != 'apk' %}<span class="badge-type">{{ a.type }}</span>{% endif %}</div>
   <div class="app-meta"><span>v{{ a.version }}</span><span>{{ a.size_formatted }}</span><span class="app-sdk">{{ a.android_ver }}+</span></div>
   <div class="app-dl">Downloads: <b>{{ a.downloads }}</b></div>
   <div class="app-actions"><a href="/app/{{ a.package }}" class="btn-versions">Versions</a><a href="/download/{{ a.package }}/{{ a.version }}" class="btn-download">Download</a></div>
  </div>
 </div>
{% endfor %}{% else %}<div class="empty-msg"><p>No apps found.</p><p>Put APK files in the <code>apks</code> folder.</p></div>{% endif %}
</div>
""" + FOOTER + r"""</body></html>"""

APP_T = r"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><meta name="description" content="Скачать {{ app_name }} для Android. APK файл, последняя версия. DroidMarket."><meta name="keywords" content="{{ app_name }}, android, apk, скачать, андроид">""" + GSC_META + r"""<meta property="og:title" content="{{ app_name }} — DroidMarket"><meta property="og:description" content="Скачать {{ app_name }} для Android. APK файл."><meta property="og:type" content="website"><meta property="og:site_name" content="DroidMarket"><meta name="twitter:card" content="summary"><title>{{ app_name }} — DroidMarket</title>
<style>""" + CSS + r"""</style>
<script>function updateProgress(){fetch('/api/progress',{signal:AbortSignal.timeout(2000)}).then(r=>r.json()).then(d=>{var c=document.querySelector('.progress-container');var i=document.querySelector('.progress-bar-inner');var t=document.querySelector('.progress-text');var m=document.querySelector('.progress-message');if(d.status==='scanning'){c.classList.add('active');i.style.width=(d.total>0?(d.current/d.total*100):0)+'%';t.textContent=d.current+'/'+d.total;m.textContent=d.message;}else{c.classList.remove('active');}}).catch(function(){});}setTimeout(function tick(){updateProgress();setTimeout(tick,2000+Math.random()*2000)},2000+Math.random()*2000);</script>
</head><body>
""" + HEADER + PROGRESS_BAR + r"""
<div class="detail-page">
 <div class="detail-card">
  <div class="detail-header">
   <div class="detail-icon"><img src="/static/icons/{{ app_icon }}" onerror="this.src='/static/icons/default_icon.png'" alt="{{ app_name }}"></div>
   <div class="detail-name"><h1>{{ app_name }}</h1><div class="pkg">{{ package }}</div></div>
  </div>
  <div class="detail-stats"><div><b>{{ total_downloads }}</b><span>Downloads</span></div><div><b>{{ versions|length }}</b><span>Versions</span></div></div>
 </div>
 {% if latest %}<a href="/download/{{ package }}/{{ latest.version }}" class="detail-download">Download Latest (v{{ latest.version }})</a>{% endif %}
 <div class="detail-card">
  <div class="versions-list"><h3>All versions ({{ versions|length }})</h3>
  {% for v in versions %}
   <div class="version-item">
    <div class="info"><span class="version">v{{ v.version }}</span><span class="detail">{{ v.size_formatted }}</span><span class="detail">Android {{ v.android_ver }}+</span>{% if v.type and v.type != 'apk' %}<span class="badge-type">{{ v.type }}</span>{% endif %}{% if v.downloads %}<span class="detail">{{ v.downloads }} downloads</span>{% endif %}</div>
    <a href="/download/{{ package }}/{{ v.version }}" class="dl-link">Download</a>
   </div>
  {% endfor %}
  </div>
 </div>
</div>
""" + FOOTER + r"""</body></html>"""

INFO_T = r"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><meta name="description" content="DroidMarket — информация о проекте. Android APK store для старых устройств и энтузиастов."><meta name="keywords" content="android, apk, droidmarket, information">""" + GSC_META + r"""<meta property="og:title" content="Info — DroidMarket"><meta property="og:description" content="DroidMarket — информация о проекте. Android APK store."><meta property="og:type" content="website"><meta property="og:site_name" content="DroidMarket"><meta name="twitter:card" content="summary"><title>Info — DroidMarket</title>
<style>""" + CSS + r"""</style></head><body>
""" + HEADER + PROGRESS_BAR + r"""
<div class="info-page">
 <div class="info-card">
  <h2>About DroidMarket</h2>
  <p>DroidMarket — a lightweight app store for old Android devices and enthusiasts.</p>
  <p style="color:#80868b;font-size:13px;">Suggestions: <b>droidmarket@mail.ru</b></p>
  <h3>Join our community</h3>
  <p><a href="https://t.me/droid_market_team" class="telegram-link" target="_blank">Telegram: @droid_market_team</a></p>
  <h3>Supported formats</h3>
  <p>APK, XAPK, APKS, APKM</p>
  <h3>Multi-version support</h3>
  <p>Each app can have multiple versions available for download.</p>
 </div>
</div>
""" + FOOTER + r"""</body></html>"""

LOGIN_T = r"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><meta name="robots" content="noindex, nofollow">""" + GSC_META + r"""<title>Login — DroidMarket</title>
<style>""" + CSS + r"""</style></head><body>
""" + HEADER + PROGRESS_BAR + r"""
<div class="box"><h2>Sign In</h2>
 <form method="post"><div class="form-group"><input type="text" name="username" placeholder="Username" required></div><div class="form-group"><input type="password" name="password" placeholder="Password" required></div><button type="submit" class="btn-green">Sign In</button></form>
</div>
""" + FOOTER + r"""</body></html>"""

PROFILE_T = r"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><meta name="robots" content="noindex, nofollow">""" + GSC_META + r"""<title>Profile — DroidMarket</title>
<style>""" + CSS + r"""</style></head><body>
""" + HEADER + PROGRESS_BAR + r"""
<div class="info-page"><div class="info-card"><h2>{{ user.username }}</h2><p style="color:#5f6368;">Registered: {{ user.created }}</p><p style="margin-top:16px;"><a href="/logout" class="btn-red" style="padding:8px 20px;">Logout</a></p></div></div>
""" + FOOTER + r"""</body></html>"""

ADM_LOGIN_T = r"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><meta name="robots" content="noindex, nofollow">""" + GSC_META + r"""<title>Admin — DroidMarket</title>
<style>""" + CSS + r"""</style></head><body>
<div class="header adm-header"><div class="header-left"><img class="header-logo-img" src="/icon.jpg" alt=""><div class="header-logo">Droid<span>Market</span> <span style="font-size:13px;font-weight:400;color:#ef9a9a;">Admin</span></div></div></div>
<div class="box"><h2>Admin Login</h2>
{% if err %}<div style="color:#d32f2f;text-align:center;margin-bottom:12px;font-size:13px;background:#ffebee;padding:8px 12px;border-radius:6px;">{{ err }}</div>{% endif %}
<form method="post"><div class="form-group"><label for="ap">Admin Password</label><input id="ap" type="password" name="password" placeholder="Enter admin password" required></div><button type="submit" class="btn-green">Login</button></form>
</div></body></html>"""

ADM_T = r"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><meta name="robots" content="noindex, nofollow">""" + GSC_META + r"""<title>Admin — DroidMarket</title>
<style>""" + CSS + r"""</style>
<script>function updateProgress(){fetch('/api/progress',{signal:AbortSignal.timeout(2000)}).then(r=>r.json()).then(d=>{var c=document.querySelector('.progress-container');var i=document.querySelector('.progress-bar-inner');var t=document.querySelector('.progress-text');var m=document.querySelector('.progress-message');if(d.status==='scanning'){c.classList.add('active');i.style.width=(d.total>0?(d.current/d.total*100):0)+'%';t.textContent=d.current+'/'+d.total;m.textContent=d.message;}else{c.classList.remove('active');}}).catch(function(){});}setTimeout(function tick(){updateProgress();setTimeout(tick,2000+Math.random()*2000)},2000+Math.random()*2000);</script>
</head><body>
<div class="header adm-header"><div class="header-left"><img class="header-logo-img" src="/icon.jpg" alt=""><div class="header-logo">Droid<span>Market</span> <span style="font-size:13px;font-weight:400;color:#ef9a9a;">Admin</span></div></div></div>
<div class="topnav"><a href="/">Site</a><a href="/admin/force_rescan">Rescan</a><a href="/admin/repair_icons">Repair Icons</a><a href="/admin/logout">Logout</a></div>
<div class="stat-bar">Apps: <b>{{ total }}</b></div>
""" + PROGRESS_BAR + r"""
<div class="table-wrap"><h3>All Apps ({{ apps|length }})</h3>
<table class="table"><thead><tr><th>Icon</th><th>Name</th><th>Package</th><th>Versions</th><th>Downloads</th><th>Action</th></tr></thead><tbody>
{% for a in apps %}<tr>
 <td><img src="/static/icons/{{ a.icon }}" onerror="this.src='/static/icons/default_icon.png'"></td>
 <td><b>{{ a.name }}</b></td>
 <td style="font-size:11px;font-family:'SF Mono','Consolas',monospace;word-break:break-all;">{{ a.package }}</td>
 <td>{{ a.versions_count }}</td><td>{{ a.total_downloads }}</td>
 <td><a href="/admin/app/{{ a.package }}" class="btn-blue btn-sm">Manage</a></td>
</tr>{% endfor %}
</tbody></table></div>
""" + FOOTER + r"""</body></html>"""

ADM_EDIT_T = r"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><meta name="robots" content="noindex, nofollow">""" + GSC_META + r"""<title>Manage {{ name }} — DroidMarket</title>
<style>""" + CSS + r"""</style>
<script>function updateProgress(){fetch('/api/progress',{signal:AbortSignal.timeout(2000)}).then(r=>r.json()).then(d=>{var c=document.querySelector('.progress-container');var i=document.querySelector('.progress-bar-inner');var t=document.querySelector('.progress-text');var m=document.querySelector('.progress-message');if(d.status==='scanning'){c.classList.add('active');i.style.width=(d.total>0?(d.current/d.total*100):0)+'%';t.textContent=d.current+'/'+d.total;m.textContent=d.message;}else{c.classList.remove('active');}}).catch(function(){});}setTimeout(function tick(){updateProgress();setTimeout(tick,2000+Math.random()*2000)},2000+Math.random()*2000);</script>
</head><body>
<div class="header adm-header"><div class="header-left"><img class="header-logo-img" src="/icon.jpg" alt=""><div class="header-logo">Droid<span>Market</span> <span style="font-size:13px;font-weight:400;color:#ef9a9a;">Admin</span></div></div></div>
<div class="topnav"><a href="/admin">&larr; Back</a></div>
""" + PROGRESS_BAR + r"""
<div class="info-page"><div class="info-card">
 <h2>{{ name }}</h2><p style="color:#5f6368;font-size:12px;">{{ package }}</p>
 <h3>Versions ({{ versions|length }})</h3>
 {% for v in versions %}
 <div class="version-item">
  <div class="info"><span class="version">v{{ v.version }}</span><span class="detail">{{ v.size_formatted }}</span><span class="detail">Android {{ v.android_ver }}+</span>{% if v.type and v.type != 'apk' %}<span class="badge-type">{{ v.type }}</span>{% endif %}</div>
  <form method="post" onsubmit="return confirm('Delete version {{ v.version }}?');" style="display:inline;"><input type="hidden" name="action" value="del_version"><input type="hidden" name="version" value="{{ v.version }}"><input type="hidden" name="csrf_token" value="{{ csrf_token }}"><button type="submit" class="btn-red btn-sm">Delete</button></form>
 </div>
 {% endfor %}
 <div class="danger-zone">
  <h3>Danger zone</h3>
  <form method="post" onsubmit="return confirm('Delete ALL versions of {{ name }}?');"><input type="hidden" name="action" value="del_all"><input type="hidden" name="csrf_token" value="{{ csrf_token }}"><button type="submit" class="btn-red">Delete All</button></form>
 </div>
</div></div>
""" + FOOTER + r"""</body></html>"""

# === ФУНКЦИИ РЕНДЕРИНГА ===
def render_html(template, **kwargs):
    """Быстрый рендеринг HTML через jinja2"""
    try:
        from jinja2 import Environment, BaseLoader
        env = Environment(loader=BaseLoader())
        template_obj = env.from_string(template)
        return template_obj.render(**kwargs)
    except:
        # Если jinja2 не установлен, простой replace
        html = template
        for key, value in kwargs.items():
            placeholder = "{{ " + key + " }}"
            html = html.replace(placeholder, str(value))
        return html

# === ОБРАБОТЧИКИ (АСИНХРОННЫЕ) ===
async def handle_index(request):
    q = request.query.get('q', '').strip().lower()
    items = []
    for pkg, data in apps_data.items():
        if data['versions']:
            latest = data['versions'][0]
            items.append({
                'package': pkg, 'name': data['name'], 'icon': data['icon'],
                'version': latest['version'], 'android_ver': latest['android_ver'],
                'size_formatted': latest['size_formatted'], 'type': latest['type'],
                'downloads': sum(v.get('downloads', 0) for v in data['versions']),
                'versions_count': len(data['versions']),
                'added_date': latest.get('added_date', '')
            })
    if q:
        items = [a for a in items if q in a['name'].lower() or q in a['package'].lower()]
    
    sort_by = request.query.get('sort', 'name')
    if sort_by == 'downloads':
        items.sort(key=lambda x: x['downloads'], reverse=True)
    elif sort_by == 'newest':
        items.sort(key=lambda x: x.get('added_date', ''), reverse=True)
    else:
        items.sort(key=lambda x: x['name'].lower())
    
    html = render_html(MAIN_T, apps=items, total=len(items), q=q,
                       progress=scan_progress, sort_by=sort_by)
    return web.Response(text=html, content_type='text/html')

async def handle_games(request):
    items = []
    for pkg, data in apps_data.items():
        if data['versions']:
            latest = data['versions'][0]
            if latest.get('type', 'apk') == 'apk':
                items.append({
                    'package': pkg, 'name': data['name'], 'icon': data['icon'],
                    'version': latest['version'], 'android_ver': latest['android_ver'],
                    'size_formatted': latest['size_formatted'], 'type': latest['type'],
                    'downloads': sum(v.get('downloads', 0) for v in data['versions']),
                    'versions_count': len(data['versions'])
                })
    items.sort(key=lambda x: x['name'].lower())
    html = render_html(MAIN_T, apps=items, total=len(items), q="",
                       page_title="Games", progress=scan_progress)
    return web.Response(text=html, content_type='text/html')

async def handle_app_detail(request):
    pkg = request.match_info.get('pkg', '')
    if pkg not in apps_data:
        raise web.HTTPNotFound()
    
    data = apps_data[pkg]
    versions = sorted(data['versions'], key=lambda v: v.get('mtime', 0), reverse=True)
    latest = versions[0] if versions else None
    
    html = render_html(APP_T, app_name=data['name'], app_icon=data['icon'],
                       package=pkg, latest=latest, versions=versions,
                       total_downloads=sum(v.get('downloads', 0) for v in versions),
                       progress=scan_progress)
    return web.Response(text=html, content_type='text/html')

async def handle_download(request):
    pkg = request.match_info.get('pkg', '')
    version = request.match_info.get('version', '')
    
    if pkg not in apps_data:
        raise web.HTTPNotFound()
    
    target_file = None
    for v in apps_data[pkg]['versions']:
        if v['version'] == version:
            target_file = v['filename']
            break
    
    if not target_file:
        raise web.HTTPNotFound()
    
    safe = os.path.normpath(target_file)
    target = (APKS_DIR / safe).resolve()
    apks_prefix = str(APKS_DIR.resolve()) + os.sep
    
    if not str(target).startswith(apks_prefix) or not target.is_file():
        raise web.HTTPNotFound()
    
    # Обновляем счетчик загрузок (буферизованно)
    async with _download_buffer_lock:
        _download_buffer[(pkg, version)] += 1
    
    return await send_file(request, str(target), 'application/vnd.android.package-archive')

async def handle_info(request):
    html = render_html(INFO_T, progress=scan_progress)
    return web.Response(text=html, content_type='text/html')

async def handle_login(request):
    if request.method == 'POST':
        data = await request.post()
        u = data.get('username', '')
        p = data.get('password', '')
        uid = hashlib.sha256(f"{u}:{p}".encode()).hexdigest()
        if uid not in users_data:
            users_data[uid] = {"username": u, "created": time.time()}
            try:
                with open(USERS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(users_data, f, ensure_ascii=False)
            except:
                pass
        resp = web.HTTPFound('/')
        resp.set_cookie('user_id', uid, max_age=86400, httponly=True)
        return resp
    
    html = render_html(LOGIN_T, progress=scan_progress)
    return web.Response(text=html, content_type='text/html')

async def handle_logout(request):
    resp = web.HTTPFound('/')
    resp.del_cookie('user_id')
    return resp

async def handle_profile(request):
    uid = request.cookies.get('user_id', '')
    if uid not in users_data:
        raise web.HTTPFound('/login')
    html = render_html(PROFILE_T, user=users_data[uid], progress=scan_progress)
    return web.Response(text=html, content_type='text/html')

async def handle_admin_login(request):
    if request.method == 'POST':
        data = await request.post()
        cfg = load_config()
        stored_hash = cfg.get("admin_password_hash") if cfg else None
        if stored_hash and check_pw_salted(data.get('password', ''), stored_hash):
            token = secrets.token_hex(16)
            admin_sessions[token] = time.time() + SESSION_LIFETIME
            resp = web.HTTPFound('/admin')
            resp.set_cookie('dm_token', token, max_age=SESSION_LIFETIME, httponly=True)
            return resp
        err = "Wrong password"
        html = render_html(ADM_LOGIN_T, err=err, progress=scan_progress)
        return web.Response(text=html, content_type='text/html')
    
    html = render_html(ADM_LOGIN_T, err=None, progress=scan_progress)
    return web.Response(text=html, content_type='text/html')

async def handle_admin_logout(request):
    token = request.cookies.get('dm_token', '')
    if token in admin_sessions:
        del admin_sessions[token]
    resp = web.HTTPFound('/admin/login')
    resp.del_cookie('dm_token')
    return resp

def admin_required(handler):
    async def wrapper(request):
        token = request.cookies.get('dm_token', '')
        if not token or token not in admin_sessions or admin_sessions[token] < time.time():
            raise web.HTTPFound('/admin/login')
        admin_sessions[token] = time.time() + SESSION_LIFETIME
        return await handler(request)
    return wrapper

@admin_required
async def handle_admin_dash(request):
    items = []
    for pkg, data in apps_data.items():
        items.append({
            'package': pkg, 'name': data['name'], 'icon': data['icon'],
            'versions_count': len(data['versions']),
            'total_downloads': sum(v.get('downloads', 0) for v in data['versions'])
        })
    items.sort(key=lambda x: x['name'].lower())
    html = render_html(ADM_T, apps=items, total=len(items), progress=scan_progress)
    return web.Response(text=html, content_type='text/html')

@admin_required
async def handle_admin_edit(request):
    pkg = request.match_info.get('pkg', '')
    if pkg not in apps_data:
        raise web.HTTPNotFound()
    
    if request.method == 'POST':
        data = await request.post()
        action = data.get('action')
        if action == 'del_version':
            version = data.get('version')
            if pkg in apps_data:
                apps_data[pkg]['versions'] = [v for v in apps_data[pkg]['versions'] if v['version'] != version]
                if not apps_data[pkg]['versions']:
                    del apps_data[pkg]
                save_data()
        elif action == 'del_all':
            if pkg in apps_data:
                del apps_data[pkg]
                save_data()
        raise web.HTTPFound('/admin')
    
    data = apps_data[pkg]
    html = render_html(ADM_EDIT_T, package=pkg, name=data['name'],
                       icon=data['icon'], versions=data['versions'],
                       csrf_token=secrets.token_hex(16), progress=scan_progress)
    return web.Response(text=html, content_type='text/html')

@admin_required
async def handle_admin_rescan(request):
    asyncio.create_task(scan_apks(force=True))
    raise web.HTTPFound('/admin')

@admin_required
async def handle_admin_repair(request):
    asyncio.create_task(repair_icons_background())
    raise web.HTTPFound('/admin')

async def repair_icons_background():
    """Ремонт иконок в фоне"""
    to_fix = []
    for pkg, info in apps_data.items():
        if info.get('icon', '') == 'default_icon.png' and info.get('versions'):
            to_fix.append(pkg)
    
    if not to_fix:
        return
    
    for pkg in to_fix:
        info = apps_data[pkg]
        for ver in info['versions']:
            fp = APKS_DIR / ver['filename']
            if not fp.exists():
                continue
            icon_name = await extract_icon_from_apk(str(fp), pkg)
            if icon_name and icon_name != 'default_icon.png':
                apps_data[pkg]['icon'] = icon_name
                save_data()
                break

# === API ENDPOINTS (OldMarket) ===
async def api_apps(request):
    q = request.query.get('q', '').strip().lower()
    items = []
    for pkg, data in apps_data.items():
        if data['versions']:
            latest = data['versions'][0]
            items.append({
                'id': data.get('id'),
                'package': pkg,
                'name': data['name'],
                'icon': data['icon'],
                'version': latest['version'],
                'android_ver': latest['android_ver'],
                'min_sdk': latest.get('min_sdk', '?'),
                'size': latest.get('size', 0),
                'size_formatted': latest['size_formatted'],
                'type': latest.get('type', 'apk'),
                'downloads': sum(v.get('downloads', 0) for v in data['versions']),
                'versions_count': len(data['versions']),
                'added_date': latest.get('added_date', '')
            })
    if q:
        items = [a for a in items if q in a['name'].lower() or q in a['package'].lower()]
    return web.json_response(items)

async def api_app_versions(request):
    app_id = int(request.match_info.get('app_id', 0))
    pkg = get_pkg_by_id(app_id)
    if not pkg:
        return web.json_response([], status=404)
    
    versions = apps_data.get(pkg, {}).get('versions', [])
    res = [{"version": v.get('version', '?'), "filename": v.get('filename', ''),
            "size": v.get('size', 0), "min_sdk": v.get('min_sdk', '?'),
            "downloads": v.get('downloads', 0)} for v in versions]
    return web.json_response(res)

async def api_download(request):
    app_id = int(request.match_info.get('app_id', 0))
    version = request.match_info.get('version', '')
    
    pkg = get_pkg_by_id(app_id)
    if not pkg:
        return web.json_response({"error": "not_found"}, status=404)
    
    target_file = None
    for v in apps_data[pkg]['versions']:
        if v['version'] == version:
            target_file = v['filename']
            break
    
    if not target_file:
        return web.json_response({"error": "version_not_found"}, status=404)
    
    safe = os.path.normpath(target_file)
    target = (APKS_DIR / safe).resolve()
    apks_prefix = str(APKS_DIR.resolve()) + os.sep
    
    if not str(target).startswith(apks_prefix) or not target.is_file():
        return web.json_response({"error": "file_not_found"}, status=404)
    
    # Обновляем счетчик (буферизованно)
    async with _download_buffer_lock:
        _download_buffer[(pkg, version)] += 1
    
    return await send_file(request, str(target), 'application/vnd.android.package-archive')

async def api_progress(request):
    return web.json_response(scan_progress)

async def api_client_latest(request):
    return web.json_response({"version": "2.3", "url": "", "changelog": "No updates available"})

async def api_client_analytics(request):
    return web.json_response({"status": "ok"})

async def api_shield_stats(request):
    """Статистика DDoS-щита (только для локального мониторинга)"""
    return web.json_response({
        'total_requests': ddos_shield.stats['total_requests'],
        'blocked_requests': ddos_shield.stats['blocked_requests'],
        'concurrent_blocked': ddos_shield.stats['concurrent_blocked'],
        'banned_ips': len(ddos_shield.banned_ips),
        'suspicious_ips': len(ddos_shield.suspicious_ips),
        'active_ips': len(ddos_shield.ip_requests),
        'rate_limits': {k: v['max'] for k, v in RATE_LIMITS.items()},
        'persistent_blocklist': BLOCKLIST_FILE.exists(),
    })

async def api_login(request):
    return web.json_response({"status": "ok", "user_id": 0, "username": "guest"})

async def api_user_profile(request):
    user_id = int(request.match_info.get('user_id', 0))
    return web.json_response({"user_id": user_id, "username": "guest", "registered": "2026-01-01"})

async def api_app_reviews(request):
    return web.json_response([])

async def api_avatars(request):
    return web.json_response([])

async def api_review_comments(request):
    return web.json_response([])

async def api_review_reaction(request):
    return web.json_response({"status": "ok"})

# === СТАТИКА ===
async def handle_static(request):
    filename = request.match_info.get('filename', '')
    subpath = request.match_info.get('subpath', '')
    
    if subpath:
        full_path = STATIC_DIR / subpath / filename
    else:
        full_path = ICONS_DIR / filename
    
    if not full_path.exists():
        if filename != 'default_icon.png':
            default = ICONS_DIR / 'default_icon.png'
            if default.exists():
                return await send_file(request, str(default), 'image/png')
        raise web.HTTPNotFound()
    
    return await send_file(request, str(full_path), 'image/png')

async def handle_icon(request):
    filename = request.match_info.get('filename', '')
    icon_path = ICONS_DIR / filename
    if icon_path.exists():
        return await send_file(request, str(icon_path), 'image/png')
    alt = filename.replace('.', '_')
    alt_path = ICONS_DIR / alt
    if alt_path.exists():
        return await send_file(request, str(alt_path), 'image/png')
    default = ICONS_DIR / 'default_icon.png'
    if default.exists():
        return await send_file(request, str(default), 'image/png')
    raise web.HTTPNotFound()

async def handle_logo(request):
    if LOGO_FILE.exists():
        return await send_file(request, str(LOGO_FILE), 'image/jpeg')
    raise web.HTTPNotFound()

async def handle_robots(request):
    host = request.host
    text = f"""User-agent: GPTBot
Disallow: /download/
Disallow: /api/download/

User-agent: Claude-Web
Disallow: /download/
Disallow: /api/download/

User-agent: Google-Extended
Disallow: /download/
Disallow: /api/download/

User-agent: CCBot
Disallow: /download/
Disallow: /api/download/

User-agent: *
Allow: /
Sitemap: https://{host}/sitemap.xml
"""
    return web.Response(text=text.strip(), content_type='text/plain')

async def handle_sitemap(request):
    urls = []
    now = datetime.utcnow().strftime('%Y-%m-%d')
    urls.append(f"""  <url><loc>https://{request.host}/</loc><lastmod>{now}</lastmod><changefreq>daily</changefreq><priority>1.0</priority></url>""")
    urls.append(f"""  <url><loc>https://{request.host}/games</loc><lastmod>{now}</lastmod><changefreq>daily</changefreq><priority>0.8</priority></url>""")
    urls.append(f"""  <url><loc>https://{request.host}/info</loc><lastmod>{now}</lastmod><changefreq>weekly</changefreq><priority>0.5</priority></url>""")
    for pkg in apps_data:
        urls.append(f"""  <url><loc>https://{request.host}/app/{pkg}</loc><lastmod>{now}</lastmod><changefreq>weekly</changefreq><priority>0.9</priority></url>""")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(urls)}
</urlset>"""
    return web.Response(text=xml, content_type='application/xml')

# === ЗАПУСК ===
async def init_app():
    """Инициализация приложения"""
    init_dirs()
    init_config()
    load_data()
    ensure_app_ids()
    
    log.info(f"Loaded {len(apps_data)} apps with numeric IDs")
    
    # Запуск фоновых задач
    asyncio.create_task(bg_scan())
    asyncio.create_task(bg_flush_downloads())
    asyncio.create_task(ddos_shield.cleanup_loop())
    
    # Создаем приложение
    app = web.Application(middlewares=[ddos_middleware])
    
    # === РОУТИНГ ===
    # SEO
    app.router.add_get('/robots.txt', handle_robots)
    app.router.add_get('/sitemap.xml', handle_sitemap)

    # Основные страницы
    app.router.add_get('/', handle_index)
    app.router.add_get('/games', handle_games)
    app.router.add_get('/info', handle_info)
    app.router.add_get('/app/{pkg:.+}', handle_app_detail)
    app.router.add_get('/download/{pkg:.+}/{version:.+}', handle_download)
    
    # Аутентификация
    app.router.add_get('/login', handle_login)
    app.router.add_post('/login', handle_login)
    app.router.add_get('/logout', handle_logout)
    app.router.add_get('/profile', handle_profile)
    
    # Админка
    app.router.add_get('/admin/login', handle_admin_login)
    app.router.add_post('/admin/login', handle_admin_login)
    app.router.add_get('/admin/logout', handle_admin_logout)
    app.router.add_get('/admin', handle_admin_dash)
    app.router.add_get('/admin/app/{pkg:.+}', handle_admin_edit)
    app.router.add_post('/admin/app/{pkg:.+}', handle_admin_edit)
    app.router.add_get('/admin/force_rescan', handle_admin_rescan)
    app.router.add_get('/admin/repair_icons', handle_admin_repair)
    
    # Статика
    app.router.add_get('/static/icons/{filename}', handle_icon)
    app.router.add_get('/static/{subpath}/{filename}', handle_static)
    app.router.add_get('/favicon.ico', handle_logo)
    app.router.add_get('/icon.jpg', handle_logo)
    app.router.add_get('/logo.png', handle_logo)
    
    # OldMarket API
    app.router.add_get('/api/apps', api_apps)
    app.router.add_get('/api/app/{app_id}/versions', api_app_versions)
    app.router.add_get('/api/download/{app_id}/{version}', api_download)
    app.router.add_get('/api/progress', api_progress)
    app.router.add_get('/api/client/latest', api_client_latest)
    app.router.add_post('/api/client/analytics', api_client_analytics)
    app.router.add_get('/api/client/analytics', api_client_analytics)
    app.router.add_get('/api/login', api_login)
    app.router.add_post('/api/login', api_login)
    app.router.add_get('/api/user/{user_id}/profile', api_user_profile)
    app.router.add_get('/api/app/{app_id}/reviews', api_app_reviews)
    app.router.add_get('/api/avatars', api_avatars)
    app.router.add_get('/api/review/{review_id}/comments', api_review_comments)
    app.router.add_post('/api/review/{review_id}/reaction', api_review_reaction)
    
    # DDoS Shield stats
    app.router.add_get('/api/shield', api_shield_stats)

    # OldMarket HTML endpoints
    app.router.add_get('/html/apps/{filename}', handle_icon)
    app.router.add_get('/html/banners/{filename}', handle_static)
    app.router.add_get('/html/screenshots/{filename}', handle_static)
    
    return app

def main():
    print("\n" + "=" * 50)
    print("  DroidMarket v3.0 with ULTIMATE DDoS PROTECTION")
    print("=" * 50)
    print(f"  Admin: /admin (password shown on first run)")
    print(f"  API: /api/apps, /api/app/1/versions")
    print(f"  DDoS Shield: {MAX_REQUESTS_PER_IP} req/10sec, {BAN_DURATION}s ban, {MAX_CONCURRENT_PER_IP} concurrent, backlog={BACKLOG_SIZE}")
    print(f"  Shield stats: /api/shield")
    print("=" * 50 + "\n")

    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = loop.run_until_complete(init_app())
    runner = web.AppRunner(app, access_log=logging.getLogger('aiohttp.access'))
    loop.run_until_complete(runner.setup())
    site = web.TCPSite(runner, '0.0.0.0', 80, backlog=BACKLOG_SIZE)
    loop.run_until_complete(site.start())

    print(f"  Server started on http://0.0.0.0:80 (backlog={BACKLOG_SIZE})")

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        loop.run_until_complete(runner.cleanup())
    finally:
        loop.close()

if __name__ == '__main__':
    main()