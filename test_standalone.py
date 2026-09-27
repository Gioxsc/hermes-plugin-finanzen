"""Standalone-Test: Plugin ohne nulleins-App, in leerer Umgebung."""
import os, sys, tempfile, shutil, base64

tmp = tempfile.mkdtemp()
os.environ["NULLEINS_HOME"] = os.path.join(tmp, "finanzen-daten")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard"))
import plugin_api
from fastapi import FastAPI
from fastapi.testclient import TestClient

app = FastAPI()
app.include_router(plugin_api.router, prefix="/api/plugins/finanzen")
c = TestClient(app)

r = c.get("/api/plugins/finanzen/overview")
print("overview (leer):", r.status_code, str(r.json().get("detail", ""))[:60])

r = c.post("/api/plugins/finanzen/daily/item",
           json={"kind": "income", "label": "Test Umsatz", "amount": "1.234,56"})
print("daily/item:", r.status_code, r.json().get("ok"), r.json().get("monthTotals"))

r = c.post("/api/plugins/finanzen/invoices/upload",
           json={"filename": "test.pdf",
                 "dataBase64": base64.b64encode(b"%PDF-fake").decode(),
                 "vendor": "Test GmbH", "amountCents": 5000})
print("upload:", r.status_code, r.json().get("ok"))
inv_id = r.json()["invoice"]["id"]

r = c.post("/api/plugins/finanzen/report/book", json={"invoiceId": inv_id, "konto": "6850"})
print("book:", r.status_code, r.json().get("ok"), "konto:", r.json().get("konto"))

r = c.get("/api/plugins/finanzen/report/susa")
print("susa:", r.status_code, len(r.json().get("entries", [])), "Zeilen")

r = c.get("/api/plugins/finanzen/report/export", params={"month": "2026-09"})
print("export:", r.status_code, r.json().get("filename"),
      len(base64.b64decode(r.json()["dataBase64"])), "Bytes")

print("\nAngelegte Dateien unter", os.environ["NULLEINS_HOME"] + ":")
for root, _, files in os.walk(os.environ["NULLEINS_HOME"]):
    for f in files:
        print("  ", os.path.relpath(os.path.join(root, f), os.environ["NULLEINS_HOME"]))
shutil.rmtree(tmp)
print("\nALLE TESTS DURCHGELAUFEN")
