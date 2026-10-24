from pathlib import Path
import base64, json, shutil, subprocess, tempfile, time, urllib.request
import websocket

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "documentacion" / "capturas"
OUT.mkdir(parents=True, exist_ok=True)
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")

def get_json(url):
    with urllib.request.urlopen(url, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))

class CDP:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=15)
        self.counter = 0
    def call(self, method, params=None):
        self.counter += 1
        request_id = self.counter
        self.ws.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        while True:
            response = json.loads(self.ws.recv())
            if response.get("id") == request_id:
                if "error" in response:
                    raise RuntimeError(response["error"])
                return response.get("result", {})
    def eval(self, expression):
        return self.call("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True})
    def screenshot(self, path):
        result = self.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
        path.write_bytes(base64.b64decode(result["data"]))

profile = tempfile.mkdtemp(prefix="flamia_chrome_")
process = subprocess.Popen([
    str(CHROME), "--headless=new", "--remote-debugging-port=9222", "--remote-allow-origins=*",
    f"--user-data-dir={profile}", "--window-size=1500,1050", "--force-device-scale-factor=1",
    "--hide-scrollbars", "--disable-notifications", "--no-first-run",
    "http://127.0.0.1:8000/accounts/login/",
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

try:
    targets = None
    for _ in range(40):
        try:
            targets = get_json("http://127.0.0.1:9222/json")
            if targets:
                break
        except Exception:
            time.sleep(0.25)
    page = next(item for item in targets if item.get("type") == "page")
    cdp = CDP(page["webSocketDebuggerUrl"])
    cdp.call("Page.enable")
    cdp.call("Runtime.enable")
    time.sleep(1.5)
    cdp.screenshot(OUT / "01_inicio_sesion.png")
    cdp.eval("document.querySelector('[name=username]').value='admin'; document.querySelector('[name=password]').value='admin123'; document.querySelector('form').submit();")
    time.sleep(2.5)
    tabs = [
        ("dashboard", "02_control_diario.png"), ("vehicles", "03_vehiculos.png"),
        ("stores", "04_tiendas.png"), ("products", "05_productos.png"),
        ("drivers", "06_repartidores.png"), ("orders", "07_entregas.png"),
        ("payments", "08_cobros.png"), ("planner", "09_planificador.png"),
        ("trips", "10_rutas.png"), ("reports", "11_reportes.png"),
        ("map", "12_mapa.png"), ("departments", "13_zonas.png"),
        ("users", "14_usuarios.png"),
    ]
    for tab, filename in tabs:
        cdp.eval(f"document.querySelector(\"button[data-tab='{tab}']\").click(); window.scrollTo(0,0);")
        time.sleep(2 if tab == "map" else 0.7)
        cdp.screenshot(OUT / filename)
    cdp.ws.close()
finally:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
    shutil.rmtree(profile, ignore_errors=True)

print(f"Capturas guardadas en {OUT}")
