import os, sys, asyncio, json, subprocess, random, time, traceback, atexit
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

app = FastAPI(title="GOST Proxy Web Manager", version="6.0.2")

# Database IP Terbaik & Cache file path
BASE_DIR = "/opt/gost-proxy"
SETTINGS_FILE = f"{BASE_DIR}/settings.conf"
IP_CACHE_FILE = f"{BASE_DIR}/ip_cache.json"
IP_HIST_FILE = f"{BASE_DIR}/ip_history.json"
PERF_FILE = f"{BASE_DIR}/proxy_performance.json"
LOG_FILE = f"{BASE_DIR}/ip_change.log"

gost_processes = {}
proxy_pool = []
current_binds = {}
current_port_list = []
current_ping = "- ms"
logs = []

def get_config_val(key, default):
    try:
        with open(SETTINGS_FILE, "r") as f:
            for line in f:
                if line.startswith(f"{key}="):
                    val = line.split("=", 1)[1].strip()
                    if val: return int(val) if isinstance(default, int) else val
    except: pass
    return default

def get_zones():
    raw = str(get_config_val("ZONES", "1081-1090"))
    zones = []
    for z in raw.split(","):
        z = z.strip()
        if "-" in z:
            parts = z.split("-")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                s, e = int(parts[0]), int(parts[1])
                if 1 <= s <= e <= 65535:
                    zones.append(f"{s}-{e}")
    return zones if zones else ["1081-1090"]

def get_zone_ports(zone_str):
    try:
        s, e = map(int, zone_str.split("-"))
        return list(range(s, e + 1))
    except:
        return []

def read_zone_binds(zone_str):
    binds = {}
    bfile = f"{BASE_DIR}/binds_{zone_str}.txt"
    if not os.path.exists(bfile):
        open(bfile, "a").close()
    try:
        with open(bfile, "r") as f:
            for line in f:
                if "|" in line:
                    port_str, proxy = line.strip().split("|", 1)
                    if port_str.isdigit():
                        binds[int(port_str)] = proxy
    except: pass
    return binds

def read_zone_pool(zone_str):
    pfile = f"{BASE_DIR}/pool_{zone_str}.txt"
    if not os.path.exists(pfile):
         open(pfile, "a").close()
    try:
        with open(pfile, "r") as f:
            return [l.strip() for l in f if l.strip()]
    except:
        return []

def read_all_configs():
    zones = get_zones()
    all_binds = {}
    port_list = []
    for z in zones:
        z_binds = read_zone_binds(z)
        for p in get_zone_ports(z):
            port_list.append((p, z))
            if p in z_binds:
                all_binds[p] = z_binds[p]
    return zones, port_list, all_binds

def log_event(port, event, proxy, ip):
    try:
        entry = {"time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "port": port, "event": event, "proxy": proxy, "ip": ip}
        with open(LOG_FILE, "a") as f: f.write(json.dumps(entry) + "\n")
        logs.append(f"[{entry['time']}] {event} on Port {port} -> {ip}")
    except: pass

def fmt_bytes(b):
    try:
        b = float(b)
        if b < 1024: return f"{b:.0f}B"
        elif b < 1024**2: return f"{b/1024:.1f}K"
        elif b < 1024**3: return f"{b/(1024**2):.1f}M"
        else: return f"{b/(1024**3):.2f}G"
    except: return "0B"

# Mengambil Status Sistem
def get_sys_metrics():
    # CPU
    cpu = 0.0
    try:
        with open('/proc/stat', 'r') as f:
            fields = f.readline().strip().split()
            total = sum(int(x) for x in fields[1:])
            idle = int(fields[4])
            time.sleep(0.1)
        with open('/proc/stat', 'r') as f:
            fields = f.readline().strip().split()
            total2 = sum(int(x) for x in fields[1:])
            idle2 = int(fields[4])
        diff_total = total2 - total
        diff_idle = idle2 - idle
        if diff_total > 0:
            cpu = round(100.0 * (1.0 - diff_idle / diff_total), 1)
    except: pass

    # RAM
    ram_pct = 0.0
    try:
        with open('/proc/meminfo', 'r') as f:
            lines = f.readlines()
            mt, ma = 0, 0
            for l in lines:
                if l.startswith('MemTotal:'): mt = int(l.split()[1]) * 1024
                elif l.startswith('MemAvailable:'): ma = int(l.split()[1]) * 1024
            if mt > 0: ram_pct = round(((mt - ma) / mt) * 100.0, 1)
    except: pass

    return {"cpu": cpu, "ram": ram_pct, "ping": current_ping}

@app.on_event("startup")
async def startup_event():
    async def run_workers():
        asyncio.create_task(sync_manager())
        asyncio.create_task(update_ping_loop())
        asyncio.create_task(continuous_health_check())
    asyncio.create_task(run_workers())

# Sync core proxy & health Check loops
async def sync_manager():
    global current_port_list, current_binds, proxy_pool
    while True:
        try:
            zones, port_list, binds = read_all_configs()
            if port_list != current_port_list:
                # terminate gost out-of-ports
                for p_ in list(gost_processes.keys()):
                    if p_ not in [x[0] for x in port_list]:
                        gost_processes[p_].terminate()
                        del gost_processes[p_]
                current_port_list = port_list
            
            # Update data pools
            new_pool = []
            for port, z in port_list:
                existing = next((x for x in proxy_pool if x["port"] == port), None)
                if not existing:
                    new_pool.append({
                        "port": port, "zone": z, "cmd": "Free", "raw_cmd": "", 
                        "ip": "-", "location": "-", "status": "Free", "activity": 0
                    })
                else:
                    new_pool.append(existing)
            proxy_pool = new_pool
            
            # Bind handling
            for port, z in port_list:
                proxy = binds.get(port, "")
                old_proxy = current_binds.get(port, "")
                if proxy != old_proxy:
                    p_obj = next((x for x in proxy_pool if x["port"] == port), None)
                    if port in gost_processes: 
                        gost_processes[port].terminate()
                        del gost_processes[port]
                    
                    if not proxy:
                        if p_obj: p_obj.update({"cmd": "Free", "raw_cmd": "", "ip": "-", "status": "Free"})
                    else:
                        parts = proxy.split(":")
                        if len(parts) >= 4:
                            host, p_port, user, pwd = parts[0], parts[1], parts[2], ":".join(parts[3:])
                            cmd = [f"{BASE_DIR}/gost", "-L", f"socks5://0.0.0.0:{port}", "-F", f"socks5://{user}:{pwd}@{host}:{p_port}"]
                            gost_processes[port] = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            if p_obj: 
                                p_obj.update({"cmd": f"{host}:{p_port}", "raw_cmd": proxy, "ip": "Checking...", "status": "Checking"})
                                asyncio.create_task(check_proxy_ip(p_obj))
            current_binds = binds.copy()
        except Exception as e:
            logs.append(f"Sync error: {str(e)}")
        await asyncio.sleep(2)

async def check_proxy_ip(p_obj):
    port = p_obj["port"]
    try:
        proc = await asyncio.create_subprocess_exec(
            "curl", "-4", "-s", "--max-time", "6", "-x", f"socks5h://127.0.0.1:{port}", "https://ipinfo.io/json",
            stdout=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0 and stdout:
            d = json.loads(stdout.decode())
            p_obj.update({"ip": d.get("ip", "-"), "location": f"{d.get('country', '')} - {d.get('region', '')}", "status": "Online"})
            log_event(port, "ONLINE", p_obj["raw_cmd"], p_obj["ip"])
            return
    except: pass
    p_obj.update({"ip": "LOS/Error", "status": "LOS"})
    log_event(port, "LOS ERROR", p_obj["raw_cmd"], "-")

async def update_ping_loop():
    global current_ping
    while True:
        try:
            proc = await asyncio.create_subprocess_exec("ping", "-c", "1", "-W", "2", "8.8.8.8", stdout=asyncio.subprocess.PIPE)
            stdout, _ = await proc.communicate()
            if proc.returncode == 0 and stdout:
                out = stdout.decode()
                current_ping = f"{out.split('time=')[1].split(' ')[0]} ms" if "time=" in out else "Timeout"
        except: current_ping = "Error"
        await asyncio.sleep(4)

async def continuous_health_check():
    while True:
        for p in proxy_pool:
            if p["status"] == "Online":
                asyncio.create_task(check_proxy_ip(p))
        await asyncio.sleep(45)

# API Routes
class ProxyBind(BaseModel):
    zone: str
    port: int
    proxy: str

@app.get("/api/dashboard")
async def get_dashboard_data():
    return {
        "system": get_sys_metrics(),
        "zones": {z: {"pool": len(read_zone_pool(z)), "binds": len(read_zone_binds(z))} for z in get_zones()},
        "proxy_pool": proxy_pool,
        "logs": logs[-15:]
    }

@app.get("/api/pool/{zone}")
async def get_pool_zone(zone: str):
    return {"zone": zone, "proxies": read_zone_pool(zone)}

@app.post("/api/add-proxy")
async def add_proxy_bulk(zone: str, payload: dict):
    proxies = payload.get("proxies", "").split("\n")
    pfile = f"{BASE_DIR}/pool_{zone}.txt"
    added = 0
    with open(pfile, "a") as f:
        for p in proxies:
            if p.strip():
                f.write(p.strip() + "\n")
                added += 1
    return {"status": "success", "added": added}

@app.post("/api/bind")
async def bind_manual(payload: ProxyBind):
    bfile = f"{BASE_DIR}/binds_{payload.zone}.txt"
    # remove existing
    lines = []
    if os.path.exists(bfile):
        with open(bfile, "r") as f:
            lines = [l.strip() for l in f if not l.startswith(f"{payload.port}|")]
    lines.append(f"{payload.port}|{payload.proxy}")
    with open(bfile, "w") as f:
        f.write("\n".join(lines) + "\n")
    return {"status": "success"}

@app.post("/api/unbind")
async def unbind_manual(zone: str, port: int):
    bfile = f"{BASE_DIR}/binds_{zone}.txt"
    if os.path.exists(bfile):
        lines = []
        with open(bfile, "r") as f:
            lines = [l.strip() for l in f if not l.startswith(f"{port}|")]
        with open(bfile, "w") as f:
            f.write("\n".join(lines) + "\n")
    return {"status": "success"}

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    with open(f"{BASE_DIR}/templates/index.html", "r") as f:
        return f.read()

def cleanup():
    for p in gost_processes.values(): p.terminate()
atexit.register(cleanup)
