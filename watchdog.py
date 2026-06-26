import subprocess, time, sys, os, socket, logging

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger("watchdog")

BASE = os.path.dirname(os.path.abspath(__file__))
SERVER_SCRIPT = os.path.join(BASE, "server.py")
CHECK_INTERVAL = 15
SSH_SUBDOMAIN = "barbaros"
SSH_HOST = "serveo.net"
server_proc = None
ssh_proc = None

def port_open(port, host="127.0.0.1"):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(3)
        s.connect((host, port))
        s.close()
        return True
    except: return False

def http_ok(port=5000):
    try:
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/")
        r = c.getresponse()
        c.close()
        return r.status == 200
    except: return False

def start_server():
    global server_proc
    if server_proc is not None:
        server_proc.kill()
        server_proc.wait()
    log.info("Starting server...")
    server_proc = subprocess.Popen([sys.executable, SERVER_SCRIPT],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    if port_open(5000):
        log.info("Server started (pid %d)" % server_proc.pid)
    else:
        log.warning("Server may not be ready yet")

def start_ssh():
    global ssh_proc
    if ssh_proc is not None:
        ssh_proc.kill()
        ssh_proc.wait()
    log.info("Connecting SSH tunnel %s.serveousercontent.com ..." % SSH_SUBDOMAIN)
    ssh_proc = subprocess.Popen([
        "ssh", "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=30",
        "-o", "ExitOnForwardFailure=yes",
        "-R", "%s:80:127.0.0.1:5000" % SSH_SUBDOMAIN,
        SSH_HOST
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(5)
    if ssh_proc.poll() is None:
        log.info("SSH tunnel connected (pid %d)" % ssh_proc.pid)
    else:
        log.warning("SSH tunnel failed to connect")

def check_ssh():
    if ssh_proc is None: return False
    return ssh_proc.poll() is None

if __name__ == "__main__":
    log.info("Watchdog started (check every %ds)" % CHECK_INTERVAL)

    if port_open(5000):
        log.info("Server already running")
    else:
        start_server()

    if check_ssh():
        log.info("SSH tunnel already running")
    else:
        start_ssh()

    while True:
        time.sleep(CHECK_INTERVAL)

        if not http_ok():
            log.warning("Server not responding, restarting...")
            start_server()

        if not check_ssh():
            log.warning("SSH tunnel down, reconnecting...")
            start_ssh()
