#!/usr/bin/env python3
"""Проверка API: /api/status и /api/init. Запуск: python test_api.py [BASE_URL]"""
import sys
import urllib.request
import json

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"

def req(method, path):
    r = urllib.request.Request(BASE + path, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:200]}
    except Exception as e:
        return None, {"error": str(e)}

print("Проверка API:", BASE)
print("-" * 50)
code, data = req("GET", "/api/status")
print("GET /api/status:", code)
print(json.dumps(data, ensure_ascii=False, indent=2))
print("-" * 50)
code, data = req("POST", "/api/init")
print("POST /api/init:", code)
print(json.dumps(data, ensure_ascii=False, indent=2))
print("-" * 50)
if code == 200 and data.get("status") in ("started", "running", "done"):
    print("✓ API работает корректно")
else:
    print("✗ Проверьте ответ выше или что сервер запущен (python app.py)")
