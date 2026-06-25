# -*- coding: utf-8 -*-
"""
DroidMarket — Play Market 2014 Style
MultiVersion Android APK Store
+ OldMarket (Android 1.6) Compatibility Layer
"""
import os, io, json, time, zipfile, threading, logging, hashlib, sys, re, atexit
import multiprocessing, secrets, shutil
from pathlib import Path
from datetime import datetime
from functools import wraps
from flask import (Flask, render_template_string, send_from_directory, send_file,
                   abort, request, redirect, url_for, make_response, session, jsonify)
from PIL import Image

# === ЛОГИ ===
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
for n in ['androguard', 'androguard.core.axml', 'androguard.core.apk']:
    logging.getLogger(n).setLevel(logging.CRITICAL)
try:
    from loguru import logger; logger.remove()
except: pass

if sys.platform == 'win32': multiprocessing.freeze_support()

log = logging.getLogger("droidmarket")
log.setLevel(logging.INFO)
fh = logging.FileHandler("server.log", encoding="utf-8")
fh.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S"))
log.addHandler(fh)
ch = logging.StreamHandler()
ch.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S"))
log.addHandler(ch)
log.propagate = False

# === ПУТИ ===
BASE_DIR = Path(__file__).parent.resolve()
APKS_DIR = BASE_DIR / "apks"
STATIC_DIR = BASE_DIR / "static"
ICONS_DIR = STATIC_DIR / "icons"
DATA_FILE = BASE_DIR / "apps_data.json"
CONFIG_FILE = BASE_DIR / "config.json"
USERS_FILE = BASE_DIR / "users.json"
LOGO_FILE = BASE_DIR / "icon.jpg"

# === КОНСТАНТЫ ===
ICON_SIZE = (128, 128)
SCAN_INTERVAL = 60
SESSION_LIFETIME = 86400

# === ПРОГРЕСС ===
scan_progress = {
    'total': 0,
    'current': 0,
    'status': 'idle',
    'message': ''
}

# === ИНИЦИАЛИЗАЦИЯ ===
def init_dirs():
    for d in (APKS_DIR, STATIC_DIR, ICONS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    if not LOGO_FILE.exists():
        try:
            img = Image.new("RGBA", (96, 96), (148, 171, 58, 255))
            img.save(LOGO_FILE, "PNG")
        except: pass
    if not (ICONS_DIR / "default_icon.png").exists():
        try:
            img = Image.new("RGBA", (128, 128), (80, 80, 80, 255))
            img.save(ICONS_DIR / "default_icon.png", "PNG", optimize=True)
        except: pass

def hash_pw(p):
    return hashlib.sha256(p.encode()).hexdigest()

def hash_pw_salted(p):
    salt = secrets.token_hex(8)
    return salt + "$" + hashlib.sha256((salt + p).encode()).hexdigest()

def check_pw_salted(p, stored):
    parts = stored.split("$", 1)
    if len(parts) != 2:
        return hash_pw(p) == stored
    return hashlib.sha256((parts[0] + p).encode()).hexdigest() == parts[1]

def init_config():
    if not CONFIG_FILE.exists():
        pw = secrets.token_hex(6)
        log.info("=" * 40)
        log.info("ADMIN PASSWORD: %s", pw)
        log.info("=" * 40)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"admin_password_hash": hash_pw_salted(pw),
                       "_note": "Password shown above on first run"}, f)
        print("\n" + "=" * 40)
        print(f"  ADMIN PASSWORD: {pw}")
        print("=" * 40 + "\n")

def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    pw = secrets.token_hex(6)
    log.warning("CONFIG MISSING — generating new admin password: %s", pw)
    print("\n*** CONFIG MISSING — NEW ADMIN PASSWORD: %s ***\n" % pw)
    cfg = {"admin_password_hash": hash_pw_salted(pw)}
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
    except: pass
    return cfg

# === ДАННЫЕ ===
apps_data = {}
users_data = {}
data_lock = threading.RLock()
admin_sessions = {}
corrupted_files = set()
scan_lock = threading.Lock()

def load_data():
    global apps_data, users_data
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
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
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                users_data.update(json.load(f))
        except: pass

def save_json(p, d):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, separators=(',', ':'))

def save_data():
    with data_lock:
        save_json(DATA_FILE, apps_data)

def record_download(package, version):
    with data_lock:
        if package in apps_data:
            for v in apps_data[package]['versions']:
                if v['version'] == version:
                    v['downloads'] = v.get('downloads', 0) + 1
                    save_json(DATA_FILE, apps_data)
                    break

def fmt_size(b):
    for u in ['B', 'KB', 'MB', 'GB']:
        if b < 1024.0:
            return f"{b:.1f} {u}"
        b /= 1024.0
    return f"{b:.1f} TB"

def api_to_android(api_level):
    api_map = {
        1: '1.0', 2: '1.1', 3: '1.5', 4: '1.6', 5: '2.0', 6: '2.0.1', 7: '2.1', 8: '2.2',
        9: '2.3', 10: '2.3.3', 11: '3.0', 12: '3.1', 13: '3.2', 14: '4.0', 15: '4.0.3',
        16: '4.1', 17: '4.2', 18: '4.3', 19: '4.4', 20: '4.4W', 21: '5.0', 22: '5.1',
        23: '6.0', 24: '7.0', 25: '7.1', 26: '8.0', 27: '8.1', 28: '9.0', 29: '10',
        30: '11', 31: '12', 32: '12L', 33: '13', 34: '14', 35: '15'
    }
    try:
        level = int(api_level)
        return api_map.get(level, f'API {level}')
    except:
        return api_level

# ==========================================
# === OLD MARKET (Android 1.6) COMPAT ===
# ==========================================
def ensure_app_ids():
    """Присваивает числовые ID всем приложениям при загрузке"""
    changed = False
    with data_lock:
        current_ids = {data.get('id') for data in apps_data.values() if data.get('id')}
        next_id = max(current_ids) + 1 if current_ids else 1
        for pkg, data in apps_data.items():
            if 'id' not in data or data['id'] is None:
                while next_id in current_ids:
                    next_id += 1
                data['id'] = next_id
                current_ids.add(next_id)
                changed = True
                log.info(f"Assigned ID {next_id} to {pkg}")
    if changed:
        save_data()

def get_pkg_by_id(app_id):
    """Находит package_name по числовому ID"""
    with data_lock:
        for pkg, data in apps_data.items():
            if data.get('id') == app_id:
                return pkg
    return None

# === ИКОНКИ ===
def safe_icon_name(pkg_name):
    safe = re.sub(r'[^\w\-.]', '_', pkg_name)[:100]
    return safe if safe else 'default'

def generate_fallback_icon(pkg_name, name=''):
    try:
        import hashlib
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
        log.info(f"Fallback icon saved: {safe_name}.png for {pkg_name}")
        return f"{safe_name}.png"
    except Exception as e:
        log.error(f"Error generating fallback icon for {pkg_name}: {e}")
        return 'default_icon.png'

def compress_icon(data, pkg_name):
    try:
        img = Image.open(io.BytesIO(data))
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        img = img.resize(ICON_SIZE, Image.Resampling.LANCZOS)
        safe_name = safe_icon_name(pkg_name)
        icon_path = ICONS_DIR / f"{safe_name}.png"
        img.save(icon_path, 'PNG', optimize=True, compress_level=9)
        log.info(f"Icon saved: {safe_name}.png for {pkg_name}")
        return f"{safe_name}.png"
    except Exception as e:
        log.error(f"Error saving icon for {pkg_name}: {e}")
        return 'default_icon.png'

def extract_icon_from_apk(fp, pkg_name):
    # --- Try androguard FIRST (reads exact manifest icon reference) ---
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
                        result = compress_icon(data, pkg_name)
                        if result and result != 'default_icon.png':
                            return result
                except:
                    continue
    except Exception as e:
        log.error(f"Error in androguard icon extraction for {pkg_name}: {e}")

    # --- Fall back to regex (skip .9.png and common library resources) ---
    try:
        with zipfile.ZipFile(fp, 'r') as zf:
            all_files = zf.namelist()
            skip_patterns = ('.9.png', 'common_signin_btn', 'abc_', 'notification_')
            priority_patterns = [
                (r'.*mipmap-xxxhdpi.*ic_launcher.*\.(png|webp)', 100),
                (r'.*drawable-xxxhdpi.*ic_launcher.*\.(png|webp|jpg)', 95),
                (r'.*mipmap-xxhdpi.*ic_launcher.*\.(png|webp)', 90),
                (r'.*drawable-xxhdpi.*ic_launcher.*\.(png|webp|jpg)', 85),
                (r'.*mipmap-xhdpi.*ic_launcher.*\.(png|webp)', 80),
                (r'.*drawable-xhdpi.*ic_launcher.*\.(png|webp|jpg)', 75),
                (r'.*mipmap-hdpi.*ic_launcher.*\.(png|webp)', 70),
                (r'.*drawable-hdpi.*ic_launcher.*\.(png|webp|jpg)', 65),
                (r'.*mipmap-mdpi.*ic_launcher.*\.(png|webp)', 60),
                (r'.*drawable-mdpi.*ic_launcher.*\.(png|webp|jpg)', 55),
                (r'.*ic_launcher.*\.(png|webp|jpg)', 50),
                (r'.*icon_free.*\.(png|webp)', 45),
                (r'.*icon.*\.(png|webp|jpg)', 40),
            ]
            candidates = []
            for pattern, priority in priority_patterns:
                for name in all_files:
                    if re.match(pattern, name, re.I):
                        if any(s in name.lower() for s in skip_patterns):
                            continue
                        candidates.append((priority, name))
            candidates.sort(key=lambda x: x[0], reverse=True)
            extracted = set()
            for _, icon_name in candidates:
                if icon_name in extracted: continue
                extracted.add(icon_name)
                try:
                    data = zf.read(icon_name)
                    if len(data) > 500:
                        result = compress_icon(data, pkg_name)
                        if result and result != 'default_icon.png':
                            return result
                except: continue
    except Exception as e:
        log.error(f"Error extracting icon for {pkg_name}: {e}")

    return generate_fallback_icon(pkg_name)

def repair_icons():
    """Пробует извлечь иконки для всех приложений с default_icon.png"""
    log.info("=== ICON REPAIR: checking apps with default_icon.png ===")
    with data_lock:
        to_fix = [(pkg, info) for pkg, info in apps_data.items()
                  if info.get('icon', '') == 'default_icon.png' and info.get('versions')]
    if not to_fix:
        log.info("No apps need icon repair")
        return
    fixed = 0
    for pkg, info in to_fix:
        for ver in info['versions']:
            fp = APKS_DIR / ver['filename']
            if not fp.exists():
                continue
            icon_name = extract_icon_from_apk(str(fp), pkg)
            if icon_name and icon_name != 'default_icon.png':
                with data_lock:
                    if pkg in apps_data:
                        apps_data[pkg]['icon'] = icon_name
                log.info(f"  REPAIRED: {pkg} -> {icon_name}")
                fixed += 1
                break
    with data_lock:
        save_json(DATA_FILE, apps_data)
    log.info(f"=== ICON REPAIR: {fixed}/{len(to_fix)} fixed ===")

# === ПАРСИНГ И СКАНИРОВАНИЕ ===
def parse_apk(fp, ftype='apk'):
    fp = Path(fp)
    if not fp.exists(): return None
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
                try: name = apk.get_element('application', 'android:label')
                except: pass
            if not name or name == pkg: name = pkg
            return {
                'package': pkg, 'name': name, 'version': ver, 'min_sdk': sdk,
                'android_ver': android_ver, 'filename': fp.name,
                'size': fp.stat().st_size, 'size_formatted': fmt_size(fp.stat().st_size),
                'mtime': fp.stat().st_mtime, 'added_date': datetime.now().strftime("%Y-%m-%d %H:%M"),
                'type': ftype, 'downloads': 0
            }
    except Exception as e:
        log.error(f"Error parsing APK {fp.name}: {e}")
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
    except: pass
    return {
        'package': fp.stem, 'name': fp.stem.replace('_', ' ').replace('-', ' '),
        'version': '?', 'min_sdk': '?', 'android_ver': '?', 'filename': fp.name,
        'size': fp.stat().st_size, 'size_formatted': fmt_size(fp.stat().st_size),
        'mtime': fp.stat().st_mtime, 'added_date': datetime.now().strftime("%Y-%m-%d %H:%M"),
        'type': ftype, 'downloads': 0
    }

def parse_archive(fp, ftype):
    fp = Path(fp)
    try:
        with zipfile.ZipFile(fp, 'r') as zf:
            apks = [f for f in zf.namelist() if f.endswith('.apk')]
            if not apks: return None
            base = next((f for f in apks if 'base.apk' in f.lower()), apks[0])
            tmp = fp.with_suffix('.temp.apk')
            with open(tmp, 'wb') as f: f.write(zf.read(base))
            r = parse_apk(str(tmp), ftype)
            try: tmp.unlink()
            except: pass
            if r:
                r['filename'] = fp.name
                return r
    except Exception as e:
        log.error(f"Error parsing archive {fp.name}: {e}")
    return None

def scan_file(fp):
    fp = Path(fp)
    ext = fp.suffix.lower()
    try:
        if ext == '.apk': return parse_apk(fp, 'apk')
        elif ext == '.xapk': return parse_archive(fp, 'xapk')
        elif ext in ('.apks', '.apkm'): return parse_archive(fp, ext[1:])
    except Exception as e:
        log.error(f"Error scanning {fp.name}: {e}")
    return None

def scan_apks(force=False):
    global scan_progress
    if not scan_lock.acquire(blocking=False):
        log.info("Scan already in progress, skipping...")
        return
    try:
        scan_progress['status'] = 'scanning'
        scan_progress['message'] = 'Collecting files...'
        files = {}
        for ext in ('*.apk', '*.xapk', '*.apks', '*.apkm'):
            for p in APKS_DIR.glob(ext):
                if p.is_file(): files[p.name] = p
        log.info(f"Found {len(files)} files in apks directory")
        existing_files = set()
        with data_lock:
            for pkg, data in apps_data.items():
                for v in data['versions']:
                    existing_files.add(v['filename'])
        new_files = {}
        for fn, fp in files.items():
            if force or fn not in existing_files:
                new_files[fn] = fp
        if not new_files:
            scan_progress['status'] = 'idle'
            scan_progress['message'] = 'No new files to scan'
            return
        total = len(new_files)
        scan_progress['total'] = total
        scan_progress['current'] = 0
        scan_progress['message'] = f'Scanning {total} new files...'
        log.info(f"=== SCAN: {total} new files ===")
        done = 0; ok = 0; t0 = time.time()
        new_data = {}
        for fn, fp in new_files.items():
            done += 1
            scan_progress['current'] = done
            scan_progress['message'] = f'Scanning {done}/{total}: {fn[:40]}...'
            try:
                r = scan_file(str(fp))
                if r:
                    pkg = r['package']
                    icon_name = extract_icon_from_apk(str(fp), pkg)
                    if pkg not in new_data:
                        existing_pkg = None
                        with data_lock:
                            if pkg in apps_data: existing_pkg = apps_data[pkg]
                        if existing_pkg:
                            old_icon = existing_pkg.get('icon', 'default_icon.png')
                            new_data[pkg] = {
                                'name': existing_pkg['name'],
                                'icon': icon_name if old_icon == 'default_icon.png' else old_icon,
                                'versions': existing_pkg['versions'].copy()
                            }
                        else:
                            new_data[pkg] = {'name': r['name'], 'icon': icon_name, 'versions': []}
                    else:
                        old_icon = new_data[pkg].get('icon', 'default_icon.png')
                        if old_icon == 'default_icon.png':
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
                    ok += 1
                    log.info(f"[{done}/{total}] OK: {r['name'][:30]} v{r['version']}")
                else:
                    corrupted_files.add(fn)
            except Exception as e:
                corrupted_files.add(fn)
                log.error(f"[{done}/{total}] ERR: {fn[:50]} - {e}")
        with data_lock:
            for pkg, data in new_data.items():
                if pkg in apps_data:
                    existing_versions = {v['filename']: v for v in apps_data[pkg]['versions']}
                    for v in data['versions']:
                        if v['filename'] not in existing_versions:
                            apps_data[pkg]['versions'].append(v)
                    apps_data[pkg]['versions'].sort(key=lambda x: x.get('mtime', 0), reverse=True)
                    apps_data[pkg]['icon'] = data['icon']
                else:
                    apps_data[pkg] = data
            save_json(DATA_FILE, apps_data)
        scan_progress['status'] = 'idle'
        scan_progress['message'] = f'Done: {ok}/{total} new files scanned'
        log.info(f"=== DONE: {ok}/{total} ok, {time.time()-t0:.1f}s ===")
    finally:
        scan_lock.release()

def bg_scan():
    time.sleep(10)
    while True:
        try: scan_apks()
        except Exception as e: log.error(f"Scanner: {e}")
        time.sleep(SCAN_INTERVAL)

def admin_required(f):
    @wraps(f)
    def dec(*a, **kw):
        t = request.cookies.get("dm_token")
        if not t or t not in admin_sessions or admin_sessions[t] < time.time():
            return redirect(url_for("admin_login"))
        admin_sessions[t] = time.time() + SESSION_LIFETIME
        return f(*a, **kw)
    return dec

# === FLASK APP ===
app = Flask(__name__)

SECRET_FILE = BASE_DIR / ".secret_key"
if SECRET_FILE.exists():
    app.secret_key = SECRET_FILE.read_text().strip()
else:
    app.secret_key = secrets.token_hex(32)
    SECRET_FILE.write_text(app.secret_key)

app.config["JSON_AS_ASCII"] = False

def gen_csrf():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]

def check_csrf():
    token = request.form.get("csrf_token")
    return token and session.get("csrf_token") and token == session["csrf_token"]

@app.before_request
def check_csrf_post():
    if request.method == "POST" and request.path.startswith("/admin") and not request.path.startswith("/admin/login"):
        if not check_csrf():
            return "CSRF validation failed", 403

@app.after_request
def add_h(r):
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["X-Frame-Options"] = "DENY"
    r.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; script-src 'self' 'unsafe-inline'"
    r.headers["Referrer-Policy"] = "same-origin"
    if request.path.startswith('/static/') or request.path in ('/icon.jpg', '/logo.png'):
        r.headers['Cache-Control'] = 'public, max-age=86400'
    else:
        r.headers['Cache-Control'] = 'no-cache'
    return r

# ==========================================
# === OLD MARKET API (Android 1.6) ===
# ==========================================
@app.route("/api/app/<int:app_id>/versions")
def om_app_versions(app_id):
    pkg = get_pkg_by_id(app_id)
    if not pkg: return jsonify([]), 404
    with data_lock:
        versions = apps_data.get(pkg, {}).get('versions', [])
        res = [{"version": v.get('version','?'), "filename": v.get('filename',''), 
                "size": v.get('size',0), "min_sdk": v.get('min_sdk','?'), 
                "downloads": v.get('downloads',0)} for v in versions]
        return jsonify(res)

@app.route("/api/download/<int:app_id>/<path:version>")
def om_download(app_id, version):
    try:
        pkg = get_pkg_by_id(app_id)
        if not pkg:
            return jsonify({"error": "not_found"}), 404
        with data_lock:
            target_file = next((v['filename'] for v in apps_data[pkg]['versions'] if v['version'] == version), None)
            if not target_file:
                return jsonify({"error": "version_not_found"}), 404
            safe = os.path.normpath(target_file)
            target = (APKS_DIR / safe).resolve()
            apks_prefix = str(APKS_DIR.resolve()) + os.sep
            if not str(target).startswith(apks_prefix) or not target.is_file():
                return jsonify({"error": "file_not_found"}), 404
        record_download(pkg, version)
        resp = send_file(str(target), as_attachment=True,
                         download_name=target.name,
                         mimetype="application/vnd.android.package-archive")
        resp.headers["Content-Length"] = str(target.stat().st_size)
        resp.headers["Accept-Ranges"] = "bytes"
        return resp
    except Exception as e:
        log.error("om_download error: %s", e)
        return jsonify({"error": "download_failed"}), 500

@app.route("/html/apps/<path:filename>")
def om_icon(filename):
    return send_from_directory(str(ICONS_DIR), filename)

@app.route("/html/banners/<path:filename>")
def om_banner(filename):
    return send_from_directory(str(STATIC_DIR), f"banners/{filename}")

@app.route("/html/screenshots/<path:filename>")
def om_screenshot(filename):
    return send_from_directory(str(STATIC_DIR), f"screenshots/{filename}")

@app.route("/logo.png")
def om_logo():
    if LOGO_FILE.exists(): return send_from_directory(str(BASE_DIR), LOGO_FILE.name)
    abort(404)

@app.route("/api/client/latest")
def om_client_latest():
    return jsonify({"version": "2.3", "url": "", "changelog": "No updates available"})

@app.route("/api/client/analytics", methods=["GET", "POST"])
def om_client_analytics():
    return jsonify({"status": "ok"})

@app.route("/api/login", methods=["GET", "POST"])
def om_login():
    return jsonify({"status": "ok", "user_id": 0, "username": "guest"})

@app.route("/api/user/<int:user_id>/profile")
def om_user_profile(user_id):
    return jsonify({"user_id": user_id, "username": "guest", "registered": "2026-01-01"})

@app.route("/api/app/<int:app_id>/reviews")
def om_app_reviews(app_id):
    return jsonify([])

@app.route("/api/avatars")
def om_avatars():
    return jsonify([])

@app.route("/api/review/<int:review_id>/comments")
def om_review_comments(review_id):
    return jsonify([])

@app.route("/api/review/<int:review_id>/reaction", methods=["POST"])
def om_review_reaction(review_id):
    return jsonify({"status": "ok"})

# ==========================================
# === DROIDMARKET WEB INTERFACE ===
# ==========================================
@app.route("/icon.jpg")
def logo():
    if LOGO_FILE.exists(): return send_from_directory(str(BASE_DIR), "icon.jpg")
    abort(404)

@app.route("/")
def index():
    q = request.args.get("q", "").strip().lower()
    with data_lock:
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
        sort_by = request.args.get("sort", "name")
        if sort_by == "downloads": items.sort(key=lambda x: x['downloads'], reverse=True)
        elif sort_by == "newest": items.sort(key=lambda x: x.get('added_date', ''), reverse=True)
        else: items.sort(key=lambda x: x['name'].lower())
        return render_template_string(MAIN_T, apps=items, total=len(items), q=q,
                                    progress=scan_progress, sort_by=sort_by)

@app.route("/games")
def games():
    with data_lock:
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
        return render_template_string(MAIN_T, apps=items, total=len(items), q="",
                                    page_title="Games", progress=scan_progress)

@app.route("/app/<path:pkg>")
def app_detail(pkg):
    with data_lock:
        if pkg not in apps_data: abort(404)
        data = apps_data[pkg]
        versions = sorted(data['versions'], key=lambda v: v.get('mtime', 0), reverse=True)
        latest = versions[0] if versions else None
        return render_template_string(APP_T, app_name=data['name'], app_icon=data['icon'],
                                    package=pkg, latest=latest, versions=versions,
                                    total_downloads=sum(v.get('downloads', 0) for v in versions),
                                    progress=scan_progress)

@app.route("/download/<path:pkg>/<path:version>")
def download_version(pkg, version):
    try:
        with data_lock:
            if pkg not in apps_data:
                return jsonify({"error": "not_found"}), 404
            target_file = next((v['filename'] for v in apps_data[pkg]['versions'] if v['version'] == version), None)
            if not target_file:
                return jsonify({"error": "version_not_found"}), 404
            safe = os.path.normpath(target_file)
            target = (APKS_DIR / safe).resolve()
            apks_prefix = str(APKS_DIR.resolve()) + os.sep
            if not str(target).startswith(apks_prefix) or not target.is_file():
                return jsonify({"error": "file_not_found"}), 404
        record_download(pkg, version)
        resp = send_file(str(target), as_attachment=True,
                         download_name=target.name,
                         mimetype="application/vnd.android.package-archive")
        resp.headers["Content-Length"] = str(target.stat().st_size)
        resp.headers["Accept-Ranges"] = "bytes"
        return resp
    except Exception as e:
        log.error("web_download error: %s", e)
        return jsonify({"error": "download_failed"}), 500

@app.route("/info")
def info():
    return render_template_string(INFO_T, progress=scan_progress)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username"); p = request.form.get("password")
        uid = hash_pw(u + ":" + p)
        if uid not in users_data:
            users_data[uid] = {"username": u, "created": time.time()}
            save_json(USERS_FILE, users_data)
        session["user_id"] = uid
        return redirect(url_for("index"))
    return render_template_string(LOGIN_T, progress=scan_progress)

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("index"))

@app.route("/profile")
def profile():
    uid = session.get("user_id")
    if not uid or uid not in users_data: return redirect(url_for("login"))
    return render_template_string(PROFILE_T, user=users_data[uid], progress=scan_progress)

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    err = None
    if request.method == "POST":
        cfg = load_config()
        stored_hash = cfg.get("admin_password_hash") if cfg else None
        if stored_hash and check_pw_salted(request.form.get("password", ""), stored_hash):
            t = secrets.token_hex(16)
            admin_sessions[t] = time.time() + SESSION_LIFETIME
            r = make_response(redirect(url_for("admin_dash")))
            r.set_cookie("dm_token", t, max_age=SESSION_LIFETIME, httponly=True, secure=False, samesite="Lax")
            return r
        err = "Wrong password"
    return render_template_string(ADM_LOGIN_T, err=err, progress=scan_progress)

@app.route("/admin/logout")
def admin_logout():
    t = request.cookies.get("dm_token")
    if t in admin_sessions: del admin_sessions[t]
    r = make_response(redirect(url_for("admin_login")))
    r.delete_cookie("dm_token")
    return r

@app.route("/admin")
@admin_required
def admin_dash():
    with data_lock:
        items = []
        for pkg, data in apps_data.items():
            items.append({
                'package': pkg, 'name': data['name'], 'icon': data['icon'],
                'versions_count': len(data['versions']),
                'total_downloads': sum(v.get('downloads', 0) for v in data['versions'])
            })
        items.sort(key=lambda x: x['name'].lower())
        return render_template_string(ADM_T, apps=items, total=len(items), progress=scan_progress)

@app.route("/admin/app/<path:pkg>", methods=["GET", "POST"])
@admin_required
def admin_edit(pkg):
    if request.method == "POST":
        action = request.form.get("action")
        if action == "del_version":
            version = request.form.get("version")
            with data_lock:
                if pkg in apps_data:
                    apps_data[pkg]['versions'] = [v for v in apps_data[pkg]['versions'] if v['version'] != version]
                    if not apps_data[pkg]['versions']: del apps_data[pkg]
                    save_json(DATA_FILE, apps_data)
        elif action == "del_all":
            with data_lock:
                if pkg in apps_data:
                    del apps_data[pkg]
                    save_json(DATA_FILE, apps_data)
        return redirect(url_for("admin_dash"))
    with data_lock:
        if pkg not in apps_data: abort(404)
        data = apps_data[pkg]
        return render_template_string(ADM_EDIT_T, package=pkg, name=data['name'],
                                    icon=data['icon'], versions=data['versions'],
                                    csrf_token=gen_csrf(), progress=scan_progress)

@app.route("/admin/force_rescan")
@admin_required
def admin_rescan():
    threading.Thread(target=lambda: scan_apks(force=True), daemon=True).start()
    return redirect(url_for("admin_dash"))

@app.route("/admin/repair_icons")
@admin_required
def admin_repair():
    threading.Thread(target=repair_icons, daemon=True).start()
    return redirect(url_for("admin_dash"))

@app.route("/api/apps")
def om_apps():
    """List all apps as JSON for Android client"""
    q = request.args.get("q", "").strip().lower()
    with data_lock:
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
        return jsonify(items)

@app.route("/api/progress")
def api_progress():
    return jsonify(scan_progress)

# === CSS ===
CSS = r"""
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; background: #f0f2f5; color: #1c1e21; min-height: 100vh; }
a { color: #1a73e8; text-decoration: none; }
a:hover { text-decoration: underline; }
.header { background: #1b5e20; color: #fff; padding: 0 20px; height: 56px; display: flex; align-items: center; justify-content: space-between; gap: 16px; position: sticky; top: 0; z-index: 100; box-shadow: 0 2px 8px rgba(0,0,0,0.15); }
.header-left { display: flex; align-items: center; gap: 12px; }
.header-logo { font-size: 22px; font-weight: 700; letter-spacing: -0.5px; }
.header-logo span { font-weight: 300; color: #a5d6a7; }
.header-search { flex: 1; max-width: 480px; }
.header-search form { display: flex; background: rgba(255,255,255,0.15); border-radius: 8px; overflow: hidden; transition: background 0.2s; }
.header-search form:focus-within { background: #fff; }
.header-search input { flex: 1; padding: 8px 14px; border: none; font-size: 14px; background: transparent; color: #fff; outline: none; }
.header-search form:focus-within input { color: #1c1e21; }
.header-search input::placeholder { color: rgba(255,255,255,0.6); }
.header-search form:focus-within input::placeholder { color: #999; }
.header-search button { padding: 8px 14px; background: transparent; border: none; cursor: pointer; color: rgba(255,255,255,0.7); font-size: 16px; }
.header-search form:focus-within button { color: #666; }
.header-actions { display: flex; gap: 6px; }
.header-actions a { color: rgba(255,255,255,0.85); text-decoration: none; font-size: 13px; font-weight: 500; padding: 6px 12px; border-radius: 6px; transition: background 0.15s; }
.header-actions a:hover { background: rgba(255,255,255,0.12); text-decoration: none; }
.topnav { background: #fff; padding: 0 20px; border-bottom: 1px solid #dadce0; display: flex; gap: 0; position: sticky; top: 56px; z-index: 99; }
.topnav a { color: #5f6368; text-decoration: none; padding: 0 20px; height: 44px; line-height: 44px; font-size: 13px; font-weight: 500; border-bottom: 2px solid transparent; transition: color 0.15s, border-color 0.15s; }
.topnav a:hover { color: #1a73e8; text-decoration: none; }
.topnav a.active { color: #1b5e20; border-bottom-color: #1b5e20; }
.stat-bar { max-width: 1200px; margin: 0 auto; padding: 12px 20px 0; font-size: 13px; color: #5f6368; }
.stat-bar b { color: #1b5e20; }
.progress-container { max-width: 1200px; margin: 0 auto; padding: 8px 20px; display: none; }
.progress-container.active { display: block; }
.progress-bar-outer { background: #e8eaed; border-radius: 10px; height: 6px; overflow: hidden; }
.progress-bar-inner { background: #1b5e20; height: 100%; width: 0%; transition: width 0.3s ease; border-radius: 10px; }
.progress-text, .progress-message { font-size: 11px; color: #5f6368; margin-top: 2px; }
.sort-bar { max-width: 1200px; margin: 0 auto; padding: 8px 20px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-size: 13px; color: #5f6368; }
.sort-bar a { color: #5f6368; text-decoration: none; padding: 4px 10px; border-radius: 16px; transition: background 0.15s, color 0.15s; }
.sort-bar a:hover { background: #e8eaed; text-decoration: none; }
.sort-bar a.active { background: #e8f5e9; color: #1b5e20; font-weight: 500; }
.sort-bar .count { margin-left: auto; color: #80868b; font-size: 12px; }
.app-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; padding: 12px 20px; max-width: 1200px; margin: 0 auto; }
.app { background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); display: flex; padding: 14px; gap: 14px; border: 1px solid #e8eaed; transition: box-shadow 0.2s, transform 0.2s; }
.app:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.12); transform: translateY(-2px); }
.app-icon { flex-shrink: 0; width: 56px; height: 56px; border-radius: 14px; overflow: hidden; background: #f0f2f5; border: 1px solid #e8eaed; }
.app-icon img { width: 100%; height: 100%; object-fit: contain; padding: 4px; }
.app-info { flex: 1; min-width: 0; }
.app-title { font-size: 14px; font-weight: 600; color: #1c1e21; margin-bottom: 2px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.app-title a { color: #1c1e21; text-decoration: none; }
.app-title a:hover { color: #1a73e8; }
.app-meta { font-size: 12px; color: #5f6368; display: flex; gap: 10px; flex-wrap: wrap; }
.app-sdk { font-size: 11px; color: #80868b; background: #f0f2f5; padding: 1px 8px; border-radius: 10px; }
.app-dl { font-size: 12px; color: #5f6368; margin-top: 4px; }
.app-dl b { color: #1b5e20; }
.app-actions { margin-top: 7px; display: flex; gap: 6px; flex-wrap: wrap; }
.btn-download { display: inline-block; background: #1b5e20; color: #fff; padding: 5px 14px; font-size: 12px; font-weight: 500; border-radius: 6px; text-decoration: none; transition: background 0.15s; }
.btn-download:hover { background: #2e7d32; text-decoration: none; }
.btn-versions { display: inline-block; background: #f0f2f5; color: #1c1e21; padding: 5px 14px; font-size: 12px; font-weight: 500; border-radius: 6px; text-decoration: none; transition: background 0.15s; }
.btn-versions:hover { background: #e8eaed; text-decoration: none; }
.badge-versions { background: #e8f5e9; color: #1b5e20; font-size: 10px; padding: 1px 7px; border-radius: 10px; font-weight: 600; }
.badge-type { background: #fff3e0; color: #e65100; font-size: 10px; padding: 1px 6px; border-radius: 4px; font-weight: 600; text-transform: uppercase; }
.detail-page { max-width: 720px; margin: 16px auto; padding: 20px; }
.detail-card { background: #fff; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid #e8eaed; overflow: hidden; margin-bottom: 12px; }
.detail-header { display: flex; gap: 16px; padding: 20px; align-items: center; }
.detail-icon { flex-shrink: 0; width: 72px; height: 72px; border-radius: 18px; background: #f0f2f5; border: 1px solid #e8eaed; overflow: hidden; }
.detail-icon img { width: 100%; height: 100%; object-fit: contain; padding: 4px; }
.detail-name { flex: 1; }
.detail-name h1 { font-size: 20px; font-weight: 600; color: #1c1e21; margin-bottom: 2px; }
.detail-name .pkg { font-size: 12px; color: #80868b; font-family: 'SF Mono', 'Consolas', monospace; }
.detail-stats { display: grid; grid-template-columns: repeat(2, 1fr); gap: 0; border-top: 1px solid #e8eaed; }
.detail-stats div { padding: 14px; text-align: center; border-right: 1px solid #e8eaed; }
.detail-stats div:last-child { border-right: none; }
.detail-stats b { display: block; font-size: 20px; color: #1b5e20; font-weight: 700; }
.detail-stats span { font-size: 11px; color: #80868b; text-transform: uppercase; letter-spacing: 0.5px; }
.detail-download { display: block; background: #1b5e20; color: #fff; text-align: center; padding: 14px; font-size: 15px; font-weight: 600; border-radius: 8px; text-decoration: none; margin: 16px 20px; transition: background 0.15s; }
.detail-download:hover { background: #2e7d32; text-decoration: none; }
.versions-list { padding: 0 20px 20px; }
.versions-list h3 { font-size: 15px; color: #1c1e21; margin-bottom: 10px; font-weight: 600; }
.version-item { background: #f8f9fa; border: 1px solid #e8eaed; border-radius: 8px; padding: 10px 14px; margin-bottom: 6px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; transition: background 0.15s; }
.version-item:hover { background: #f0f2f5; }
.version-item .info { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.version-item .version { font-weight: 600; color: #1b5e20; font-size: 13px; }
.version-item .detail { font-size: 12px; color: #5f6368; }
.version-item .dl-link { color: #1a73e8; font-weight: 500; text-decoration: none; font-size: 13px; padding: 4px 10px; border-radius: 4px; transition: background 0.15s; }
.version-item .dl-link:hover { background: #e8f0fe; text-decoration: none; }
.box { max-width: 400px; margin: 60px auto; background: #fff; padding: 36px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid #e8eaed; }
.box h2 { font-size: 20px; color: #1c1e21; margin-bottom: 24px; text-align: center; font-weight: 600; }
.form-group { margin-bottom: 16px; }
.form-group label { display: block; font-size: 13px; color: #5f6368; margin-bottom: 4px; font-weight: 500; }
.form-group input { width: 100%; padding: 10px 14px; border: 1px solid #dadce0; border-radius: 8px; font-size: 14px; outline: none; transition: border-color 0.15s; }
.form-group input:focus { border-color: #1a73e8; box-shadow: 0 0 0 2px rgba(26,115,232,0.15); }
.btn-green { display: inline-block; background: #1b5e20; color: #fff; padding: 10px 24px; font-size: 14px; font-weight: 600; border: none; border-radius: 8px; cursor: pointer; width: 100%; transition: background 0.15s; }
.btn-green:hover { background: #2e7d32; }
.btn-red { display: inline-block; background: #d32f2f; color: #fff; padding: 8px 18px; font-size: 13px; font-weight: 600; border: none; border-radius: 6px; cursor: pointer; transition: background 0.15s; }
.btn-red:hover { background: #b71c1c; }
.btn-blue { display: inline-block; background: #1a73e8; color: #fff; padding: 6px 14px; font-size: 12px; border: none; border-radius: 6px; cursor: pointer; text-decoration: none; transition: background 0.15s; }
.btn-blue:hover { background: #1557b0; text-decoration: none; }
.btn-sm { padding: 4px 10px; font-size: 11px; }
.adm-header { background: #b71c1c !important; }
.table-wrap { background: #fff; padding: 20px; max-width: 1200px; margin: 12px auto; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid #e8eaed; }
.table-wrap h3 { font-size: 15px; color: #1c1e21; margin-bottom: 14px; }
.table { width: 100%; border-collapse: collapse; font-size: 13px; }
.table th { text-align: left; padding: 10px 12px; background: #f8f9fa; color: #5f6368; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid #dadce0; }
.table td { padding: 10px 12px; border-bottom: 1px solid #e8eaed; vertical-align: middle; }
.table td img { width: 32px; height: 32px; border-radius: 8px; object-fit: contain; background: #f0f2f5; padding: 3px; }
.info-page { max-width: 650px; margin: 16px auto; }
.info-card { background: #fff; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid #e8eaed; padding: 28px; }
.info-page h2 { font-size: 20px; color: #1c1e21; margin-bottom: 16px; font-weight: 600; }
.info-page h3 { font-size: 16px; color: #1b5e20; margin-bottom: 12px; margin-top: 24px; font-weight: 600; }
.info-page p { margin-bottom: 8px; color: #5f6368; line-height: 1.5; }
.telegram-link { display: inline-block; background: #1a73e8; color: #fff; padding: 8px 20px; border-radius: 8px; text-decoration: none; font-weight: 500; transition: background 0.15s; }
.telegram-link:hover { background: #1557b0; text-decoration: none; }
.nav-bottom { max-width: 1200px; margin: 20px auto 0; padding: 16px 20px; text-align: center; border-top: 1px solid #e8eaed; }
.nav-bottom a { color: #5f6368; text-decoration: none; margin: 0 14px; font-size: 13px; transition: color 0.15s; }
.nav-bottom a:hover { color: #1a73e8; }
.footer { background: #1b5e20; color: #fff; text-align: center; padding: 16px 10px; font-size: 12px; margin-top: 0; }
.footer .team { color: #a5d6a7; font-weight: 600; }
.empty-msg { text-align: center; padding: 60px 20px; color: #80868b; }
.empty-msg p { margin-bottom: 6px; font-size: 14px; }
.empty-msg code { background: #f0f2f5; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
.danger-zone { margin-top: 20px; padding: 16px 20px; background: #fff3e0; border: 1px solid #ffcc02; border-radius: 8px; }
.danger-zone h3 { color: #e65100 !important; font-size: 14px; margin-top: 0 !important; }
@media (max-width: 768px) {
  .header { padding: 0 12px; gap: 8px; }
  .header-search { max-width: 100%; }
  .header-actions a { padding: 6px 8px; font-size: 12px; }
  .app-list { grid-template-columns: 1fr; padding: 10px; gap: 10px; }
  .detail-page { padding: 10px; }
  .detail-header { flex-direction: column; text-align: center; }
  .detail-stats { grid-template-columns: repeat(2, 1fr); }
}
"""

# === ШАБЛОНЫ ===
HEADER = r"""
<div class="header">
 <div class="header-left"><div class="header-logo">Droid<span>Market</span></div></div>
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
<html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>DroidMarket</title>
<style>""" + CSS + r"""</style>
<script>function updateProgress(){fetch('/api/progress').then(r=>r.json()).then(d=>{var c=document.querySelector('.progress-container');var i=document.querySelector('.progress-bar-inner');var t=document.querySelector('.progress-text');var m=document.querySelector('.progress-message');if(d.status==='scanning'){c.classList.add('active');i.style.width=(d.total>0?(d.current/d.total*100):0)+'%';t.textContent=d.current+'/'+d.total;m.textContent=d.message;}else{c.classList.remove('active');}}).catch(function(){});}setInterval(updateProgress,1000);</script>
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
<html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{{ app_name }} — DroidMarket</title>
<style>""" + CSS + r"""</style>
<script>function updateProgress(){fetch('/api/progress').then(r=>r.json()).then(d=>{var c=document.querySelector('.progress-container');var i=document.querySelector('.progress-bar-inner');var t=document.querySelector('.progress-text');var m=document.querySelector('.progress-message');if(d.status==='scanning'){c.classList.add('active');i.style.width=(d.total>0?(d.current/d.total*100):0)+'%';t.textContent=d.current+'/'+d.total;m.textContent=d.message;}else{c.classList.remove('active');}}).catch(function(){});}setInterval(updateProgress,1000);</script>
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
<html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Info — DroidMarket</title>
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
<html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Login — DroidMarket</title>
<style>""" + CSS + r"""</style></head><body>
""" + HEADER + PROGRESS_BAR + r"""
<div class="box"><h2>Sign In</h2>
 <form method="post"><div class="form-group"><input type="text" name="username" placeholder="Username" required></div><div class="form-group"><input type="password" name="password" placeholder="Password" required></div><button type="submit" class="btn-green">Sign In</button></form>
</div>
""" + FOOTER + r"""</body></html>"""

PROFILE_T = r"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Profile — DroidMarket</title>
<style>""" + CSS + r"""</style></head><body>
""" + HEADER + PROGRESS_BAR + r"""
<div class="info-page"><div class="info-card"><h2>{{ user.username }}</h2><p style="color:#5f6368;">Registered: {{ user.created }}</p><p style="margin-top:16px;"><a href="/logout" class="btn-red" style="padding:8px 20px;">Logout</a></p></div></div>
""" + FOOTER + r"""</body></html>"""

ADM_LOGIN_T = r"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Admin — DroidMarket</title>
<style>""" + CSS + r"""</style></head><body>
<div class="header adm-header"><div class="header-left"><div class="header-logo">Droid<span>Market</span> <span style="font-size:13px;font-weight:400;color:#ef9a9a;">Admin</span></div></div></div>
<div class="box"><h2>Admin Login</h2>
{% if err %}<div style="color:#d32f2f;text-align:center;margin-bottom:12px;font-size:13px;background:#ffebee;padding:8px 12px;border-radius:6px;">{{ err }}</div>{% endif %}
<form method="post"><div class="form-group"><label for="ap">Admin Password</label><input id="ap" type="password" name="password" placeholder="Enter admin password" required></div><button type="submit" class="btn-green">Login</button></form>
</div></body></html>"""

ADM_T = r"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Admin — DroidMarket</title>
<style>""" + CSS + r"""</style>
<script>function updateProgress(){fetch('/api/progress').then(r=>r.json()).then(d=>{var c=document.querySelector('.progress-container');var i=document.querySelector('.progress-bar-inner');var t=document.querySelector('.progress-text');var m=document.querySelector('.progress-message');if(d.status==='scanning'){c.classList.add('active');i.style.width=(d.total>0?(d.current/d.total*100):0)+'%';t.textContent=d.current+'/'+d.total;m.textContent=d.message;}else{c.classList.remove('active');}}).catch(function(){});}setInterval(updateProgress,1000);</script>
</head><body>
<div class="header adm-header"><div class="header-left"><div class="header-logo">Droid<span>Market</span> <span style="font-size:13px;font-weight:400;color:#ef9a9a;">Admin</span></div></div></div>
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
<html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Manage {{ name }} — DroidMarket</title>
<style>""" + CSS + r"""</style>
<script>function updateProgress(){fetch('/api/progress').then(r=>r.json()).then(d=>{var c=document.querySelector('.progress-container');var i=document.querySelector('.progress-bar-inner');var t=document.querySelector('.progress-text');var m=document.querySelector('.progress-message');if(d.status==='scanning'){c.classList.add('active');i.style.width=(d.total>0?(d.current/d.total*100):0)+'%';t.textContent=d.current+'/'+d.total;m.textContent=d.message;}else{c.classList.remove('active');}}).catch(function(){});}setInterval(updateProgress,1000);</script>
</head><body>
<div class="header adm-header"><div class="header-left"><div class="header-logo">Droid<span>Market</span> <span style="font-size:13px;font-weight:400;color:#ef9a9a;">Admin</span></div></div></div>
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

# === MAIN ===
def cleanup():
    for p in multiprocessing.active_children():
        try: p.terminate()
        except: pass

atexit.register(cleanup)

def main():
    log.info("DroidMarket starting...")
    init_dirs()
    init_config()
    load_data()
    ensure_app_ids()  # Присваиваем числовые ID для OldMarket
    log.info(f"Loaded {len(apps_data)} apps with numeric IDs")
    threading.Thread(target=bg_scan, daemon=True).start()
    try:
        scan_apks()
    except KeyboardInterrupt:
        log.info("Interrupted"); cleanup()
    except Exception as e:
        log.error(f"Scan: {e}")
    try:
        repair_icons()
    except Exception as e:
        log.error(f"Icon repair: {e}")
    log.info("http://localhost:5000 | Admin: /admin")
    log.info("OldMarket API: http://localhost:5000/api/app/1/versions")
    try:
        app.run(host="0.0.0.0", port=5000, debug=False, threaded=True, use_reloader=False)
    except KeyboardInterrupt:
        log.info("Stopped"); cleanup()

if __name__ == "__main__":
    main()