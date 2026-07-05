#!/usr/bin/env python3
"""DDoS stress-test for DroidMarket /api/shield"""
import asyncio, aiohttp, time, sys, random, json
from urllib.parse import urljoin

TARGET = "http://127.0.0.1"

# === НАБОР МУСОРНЫХ ЗАПРОСОВ ===
DANGEROUS_PATHS = [
    '/wp-admin', '/phpmyadmin', '/.env', '/.git', '/cgi-bin',
    '/shell', '/cmd', '/exec', '/adminer', '/mysql', '/wp-login',
    '/xmlrpc.php', '/actuator', '/console', '/backup', '/dump',
    '/debug', '/dev', '/log', '/logs', '/trace', '/status',
    '/metrics', '/healthz', '/jenkins', '/grafana', '/prometheus',
    '/kibana', '/swagger', '/api/swagger', '/api/v1/', '/api/v2/',
    '/api/docs',
]

FAKE_UAS = [
    '', 'curl', 'python', 'Go-http-client', 'Wget', 'Mozilla', 'Chrome',
]

BIG_PAYLOAD = "A" * (1024 * 11)

results = {"ok": 0, "blocked_429": 0, "blocked_403": 0, "blocked_413": 0, "errors": 0}
lock = asyncio.Lock()

async def report():
    while True:
        await asyncio.sleep(1)
        async with lock:
            r = dict(results)
        total = sum(r.values()) or 1
        print(
            f"  OK={r['ok']} 429={r['blocked_429']} "
            f"403={r['blocked_403']} 413={r['blocked_413']} "
            f"ERR={r['errors']}  total={sum(r.values())}  "
            f"block%={(r['blocked_429']+r['blocked_403']+r['blocked_413'])/total*100:.0f}%"
        )

async def shoot(session, path, method="GET", headers=None, data=None):
    url = urljoin(TARGET, path)
    try:
        if method == "POST":
            async with session.post(url, headers=headers, data=data, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                code = resp.status
        else:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                code = resp.status
    except (asyncio.TimeoutError, aiohttp.ClientError, OSError):
        code = 0

    async with lock:
        if code == 200:
            results["ok"] += 1
        elif code == 429:
            results["blocked_429"] += 1
        elif code == 403:
            results["blocked_403"] += 1
        elif code == 413:
            results["blocked_413"] += 1
        else:
            results["errors"] += 1

async def worker_pool(size, coro_factory, label):
    """Запускает `size` конкурентных корутин одной фабрики."""
    print(f"\n>>> {label} ({size} workers) <<<")
    async with aiohttp.ClientSession() as session:
        tasks = [coro_factory(session) for _ in range(size)]
        await asyncio.gather(*tasks)
    print(f"<<< {label} done >>>")

async def flood_normal(session):
    """Бесконечный поток нормальных запросов к /api/apps"""
    while True:
        await shoot(session, "/api/apps")
        await asyncio.sleep(0.01)

async def flood_dangerous(session):
    """Штурм опасных путей"""
    while True:
        path = random.choice(DANGEROUS_PATHS)
        await shoot(session, path)
        await asyncio.sleep(0.005)

async def flood_no_ua(session):
    """Запросы без/с коротким User-Agent"""
    while True:
        ua = random.choice(FAKE_UAS)
        headers = {"User-Agent": ua} if ua else {}
        path = random.choice(["/api/apps", "/", "/games", "/info"])
        await shoot(session, path, headers=headers)
        await asyncio.sleep(0.005)

async def flood_big_body(session):
    """POST с большим телом (не API — должно резаться)"""
    while True:
        path = random.choice(["/login", "/admin/login"])
        await shoot(session, path, method="POST",
                     data={"username": "test", "password": BIG_PAYLOAD})
        await asyncio.sleep(0.01)

async def flood_burst(session):
    """Максимум запросов за 1 секунду с одного IP (burst)"""
    paths = ["/api/apps"] * 50 + ["/"] * 50 + ["/games"] * 50
    for path in paths:
        await shoot(session, path)

async def flood_concurrent_attack(session):
    """Тысяча конкурентных запросов одновременно"""
    paths = ["/api/apps", "/", "/games", "/info",
             "/app/com.example.app", "/api/progress"]
    tasks = []
    for _ in range(200):
        p = random.choice(paths)
        tasks.append(shoot(session, p))
    await asyncio.gather(*tasks)

async def fetch_shield_stats(session):
    """Читает статистику /api/shield"""
    try:
        async with session.get(urljoin(TARGET, "/api/shield"),
                               timeout=aiohttp.ClientTimeout(total=3)) as resp:
            if resp.status == 200:
                return await resp.json()
    except:
        pass
    return None

async def main():
    print("=" * 60)
    print("  DroidMarket DDoS Shield — STRESS TEST")
    print(f"  Target: {TARGET}")
    print("=" * 60)

    # Фоновый отчёт
    asyncio.create_task(report())

    # === Фаза 1: нормальная нагрузка (проверка лимита 120/10с) ===
    print("\n=== ФАЗА 1: Нормальная нагрузка (200 конкурентных) ===")
    async with aiohttp.ClientSession() as s:
        await flood_concurrent_attack(s)
    await asyncio.sleep(0.5)

    # === Фаза 2: смешанная атака ===
    print("\n=== ФАЗА 2: Смешанная атака (200 workers, все виды) ===")
    async with aiohttp.ClientSession() as session:
        tasks = []
        for _ in range(50):
            tasks.append(asyncio.create_task(flood_normal(session)))
            tasks.append(asyncio.create_task(flood_dangerous(session)))
            tasks.append(asyncio.create_task(flood_no_ua(session)))
            tasks.append(asyncio.create_task(flood_big_body(session)))
        await asyncio.sleep(15)
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    await asyncio.sleep(0.5)

    # === Фаза 3: Burst-атака ===
    print("\n=== ФАЗА 3: Burst (150 запросов за 1 секунду) ===")
    for _ in range(3):
        async with aiohttp.ClientSession() as s:
            await flood_burst(s)
    await asyncio.sleep(0.5)

    # === Фаза 4: concurrent overload ===
    print("\n=== ФАЗА 4: Concurrent overload (50 потоков, 500 запросов каждый) ===")
    async with aiohttp.ClientSession() as session:
        workers = [flood_concurrent_attack(session) for _ in range(50)]
        await asyncio.gather(*workers)
    await asyncio.sleep(1)

    # === Итоговая статистика ===
    async with aiohttp.ClientSession() as s:
        stats = await fetch_shield_stats(s)

    async with lock:
        r = dict(results)

    total = sum(r.values())
    print("\n" + "=" * 60)
    print("  ИТОГИ СТРЕСС-ТЕСТА")
    print("=" * 60)
    print(f"  Всего запросов:          {total}")
    print(f"  Пропущено (OK 200):      {r['ok']}")
    print(f"  Заблокировано (429):     {r['blocked_429']}")
    print(f"  Заблокировано (403):     {r['blocked_403']}")
    print(f"  Заблокировано (413):     {r['blocked_413']}")
    print(f"  Ошибок/таймаутов:        {r['errors']}")
    if total:
        print(f"  Процент блокировки:      {(r['blocked_429']+r['blocked_403']+r['blocked_413'])/total*100:.1f}%")
    print()

    if stats:
        print("  Статистика DDoS-щита:")
        for k, v in stats.items():
            print(f"    {k}: {v}")
    else:
        print("  /api/shield недоступен")

    print("=" * 60)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nТест прерван пользователем")
