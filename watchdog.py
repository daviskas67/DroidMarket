import subprocess, time, sys, os, socket, logging

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger("watchdog")

SERVER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py")
CHECK_INTERVAL = 15
SERVER_PORT = 5000
proc = None

def is_port_open(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(3)
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except: return False

def is_http_alive():
    try:
        import urllib.request
        urllib.request.urlopen("http://127.0.0.1:%d/" % SERVER_PORT, timeout=5)
        return True
    except: return False

def start_server():
    global proc
    if proc is not None:
        proc.kill()
        proc.wait()
    log.info("Starting server...")
    proc = subprocess.Popen([sys.executable, SERVER_SCRIPT],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    if is_port_open(SERVER_PORT):
        log.info("Server started (pid %d)" % proc.pid)
    else:
        log.warning("Server may not be ready yet")

def check_ssh_tunnel():
    try:
        r = subprocess.run(["ssh", "-O", "check", "serveo"],
            capture_output=True, timeout=5, text=True)
        return r.returncode == 0
    except: return None

if __name__ == "__main__":
    log.info("Watchdog started (check every %ds)" % CHECK_INTERVAL)

    if is_port_open(SERVER_PORT):
        log.info("Server already running")
    else:
        start_server()

    while True:
        time.sleep(CHECK_INTERVAL)

        if not is_http_alive():
            log.warning("Server not responding, restarting...")
            start_server()
        else:
            ssh = check_ssh_tunnel()
            if ssh is False:
                log.warning("SSH tunnel to serveo may be down")
