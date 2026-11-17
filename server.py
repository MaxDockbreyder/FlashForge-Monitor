"""
FlashForge Dashboard - Backend (English)
========================================
Installation:
    pip install flashforge-python-api flask

Start:
    python server.py

Then open in browser:
    http://localhost:5000
"""

import asyncio
import base64
import math
import json
import os
import re
import tempfile
from pathlib import Path
from flask import Flask, render_template, jsonify, request

app = Flask(__name__)

DEFAULT_PRINTERS = []

PRINTERS_FILE = Path(__file__).with_name("printers.json")

def load_printers():
    """Load user-configured printers, falling back to the bundled defaults."""
    if not PRINTERS_FILE.exists():
        return [dict(p) for p in DEFAULT_PRINTERS]
    try:
        with PRINTERS_FILE.open("r", encoding="utf-8") as f:
            printers = json.load(f)
        if not isinstance(printers, list):
            raise ValueError("printers.json must contain a JSON array")
        clean = []
        seen_ids = set()
        for printer in printers:
            if not isinstance(printer, dict):
                continue
            required = ("id", "name", "ip", "serial", "check_code")
            if not all(isinstance(printer.get(key), str) and printer[key].strip() for key in required):
                app.logger.warning("Skipping incomplete printer entry in %s", PRINTERS_FILE)
                continue
            if printer["id"] in seen_ids:
                app.logger.warning("Skipping duplicate printer ID %r in %s", printer["id"], PRINTERS_FILE)
                continue
            seen_ids.add(printer["id"])
            clean.append(printer)
        return clean
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        app.logger.error("Could not read %s: %s", PRINTERS_FILE, exc)
        return [dict(p) for p in DEFAULT_PRINTERS]

def save_printers(printers):
    PRINTERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix="printers-", suffix=".json", dir=PRINTERS_FILE.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(printers, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(temp_path, PRINTERS_FILE)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

PRINTERS = load_printers()

def get_printer_cfg(printer_id):
    global PRINTERS
    PRINTERS = load_printers()
    return next((p for p in PRINTERS if p.get("id") == printer_id), None)


def seconds_to_time(seconds):
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(seconds) or seconds <= 0:
        return None
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def normalize_progress(value):
    if value is None:
        return 0.0
    try:
        value = float(value)
        if not math.isfinite(value):
            return 0.0
        percent = value * 100 if 0 <= value <= 1 else value
        return round(min(100.0, max(0.0, percent)), 1)
    except (ValueError, TypeError, OverflowError):
        return 0.0


def run_async(coro):
    """Safely run async coroutines from sync Flask handlers."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


async def query_printer(cfg, load_thumbnail=True):
    result = {
        "id":                 cfg["id"],
        "name":               cfg["name"],
        "ip":                 cfg["ip"],
        "camera_url":         cfg.get("camera_url", None),
        "online":             False,
        "error":              None,
        "state":              "offline",
        "file":               None,
        "progress":           0.0,
        "layer_current":      None,
        "layer_total":        None,
        "time_remaining":     None,
        "time_elapsed":       None,
        "temp_nozzle":        0,
        "temp_nozzle_target": 0,
        "temp_bed":           0,
        "temp_bed_target":    0,
        "thumbnail":          None,
        "lights_on":          False,
    }

    if not cfg.get("ip"):
        result["error"] = "IP not configured"
        return result

    try:
        from flashforge import FlashForgeClient
        from flashforge.client import FiveMClientConnectionOptions

        options = FiveMClientConnectionOptions(
            http_port=8898,
            tcp_port=8899,
            led_control_override=True,
        )

        async with FlashForgeClient(
            cfg["ip"], cfg["serial"], cfg["check_code"], options=options
        ) as client:
            if not await client.initialize():
                result["error"] = "Connection failed"
                return result

            result["online"] = True

            info = await client.get_printer_status()
            if info:
                state = getattr(info, "machine_state", None)
                result["state"] = state.value if hasattr(state, "value") else str(state)

                result["file"]          = getattr(info, "print_file_name", None)
                raw_prog                = getattr(info, "print_progress", None)
                result["progress"]      = normalize_progress(raw_prog)
                result["layer_current"] = getattr(info, "current_print_layer", None)
                result["layer_total"]   = getattr(info, "total_print_layers", None)
                result["lights_on"]     = bool(getattr(info, "lights_on", False))

                elapsed_sec = getattr(info, "print_duration", None)
                result["time_elapsed"]  = seconds_to_time(elapsed_sec) if elapsed_sec else "-"

                prog_pct = result["progress"]
                try:
                    elapsed_seconds = float(elapsed_sec)
                except (TypeError, ValueError, OverflowError):
                    elapsed_seconds = 0.0
                if (math.isfinite(elapsed_seconds) and elapsed_seconds > 0
                        and 0 < prog_pct < 100):
                    remaining = (elapsed_seconds / prog_pct) * (100 - prog_pct)
                    result["time_remaining"] = seconds_to_time(remaining)
                else:
                    result["time_remaining"] = "-"

                extruder = getattr(info, "extruder", None)
                bed      = getattr(info, "print_bed", None)
                if extruder:
                    result["temp_nozzle"]        = int(getattr(extruder, "current", 0) or 0)
                    result["temp_nozzle_target"] = int(getattr(extruder, "set", 0) or 0)
                if bed:
                    result["temp_bed"]        = int(getattr(bed, "current", 0) or 0)
                    result["temp_bed_target"] = int(getattr(bed, "set", 0) or 0)

            # Load thumbnail
            if result["file"] and load_thumbnail:
                try:
                    thumb_bytes = await client.files.get_gcode_thumbnail(result["file"])
                    if thumb_bytes:
                        b64 = base64.b64encode(thumb_bytes).decode("utf-8")
                        result["thumbnail"] = f"data:image/png;base64,{b64}"
                except Exception:
                    pass

                if not result["thumbnail"]:
                    try:
                        thumb_info = await client.tcp_client.get_thumbnail(result["file"])
                        if thumb_info and hasattr(thumb_info, "to_base64_data_url"):
                            result["thumbnail"] = thumb_info.to_base64_data_url()
                        elif thumb_info and hasattr(thumb_info, "get_image_bytes"):
                            img = thumb_info.get_image_bytes()
                            if img:
                                b64 = base64.b64encode(img).decode("utf-8")
                                result["thumbnail"] = f"data:image/png;base64,{b64}"
                    except Exception:
                        pass

            # Fallback temperatures
            if result["temp_nozzle"] == 0:
                try:
                    temp = await client.get_temperatures()
                    if temp:
                        ext = temp.get_extruder_temp() if hasattr(temp, "get_extruder_temp") else None
                        bed = temp.get_bed_temp() if hasattr(temp, "get_bed_temp") else None
                        if ext:
                            result["temp_nozzle"]        = int(getattr(ext, "current", 0) or 0)
                            result["temp_nozzle_target"] = int(getattr(ext, "set", 0) or 0)
                        if bed:
                            result["temp_bed"]        = int(getattr(bed, "current", 0) or 0)
                            result["temp_bed_target"] = int(getattr(bed, "set", 0) or 0)
                except Exception:
                    pass

    except ImportError:
        result["error"] = "flashforge-python-api missing"
    except ConnectionRefusedError:
        result["error"] = "Connection refused"
    except TimeoutError:
        result["error"] = "Connection timeout"
    except Exception as e:
        result["error"] = str(e)

    return result


async def all_printers():
    global PRINTERS
    PRINTERS = load_printers()
    tasks = [query_printer(cfg) for cfg in PRINTERS]
    return await asyncio.gather(*tasks)


async def set_led(cfg, turn_on: bool) -> dict:
    if not cfg.get("ip"):
        return {"success": False, "error": "IP not configured"}

    try:
        from flashforge import FlashForgeClient
        from flashforge.client import FiveMClientConnectionOptions

        options = FiveMClientConnectionOptions(
            http_port=8898,
            tcp_port=8899,
            led_control_override=True,
        )
        async with FlashForgeClient(
            cfg["ip"], cfg["serial"], cfg["check_code"], options=options
        ) as client:
            if not await client.initialize():
                return {"success": False, "error": "Connection failed"}

            ok = await (client.control.set_led_on() if turn_on else client.control.set_led_off())
            return {"success": ok, "lights_on": turn_on if ok else None}

    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Routes ─────────────────────────────────────────────────────────────────────

def validate_printer_payload(data):
    if not isinstance(data, dict):
        return None, "Expected a JSON object"
    values = {}
    for key in ("name", "ip", "serial", "check_code", "camera_url"):
        value = data.get(key, "")
        if value is None and key == "camera_url":
            value = ""
        if not isinstance(value, str):
            return None, f"Field '{key}' must be text"
        values[key] = value.strip()
    if not all(values[key] for key in ("name", "ip", "serial", "check_code")):
        return None, "Name, IP address, serial number and check code are required"
    if len(values["name"]) > 80 or len(values["serial"]) > 120 or len(values["check_code"]) > 120:
        return None, "One or more fields are too long"
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", values["ip"]):
        return None, "Enter a valid IP address or hostname"
    if values["camera_url"] and (len(values["camera_url"]) > 500 or not re.fullmatch(r"https?://[^\s]+", values["camera_url"], re.IGNORECASE)):
        return None, "Camera URL must start with http:// or https:// and be at most 500 characters"
    printer = {key: values[key] for key in ("name", "ip", "serial", "check_code")}
    if values["camera_url"]:
        printer["camera_url"] = values["camera_url"]
    return printer, None


def unique_printer_id(name, used_ids):
    base_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "printer"
    printer_id, suffix = base_id, 2
    while printer_id in used_ids:
        printer_id = f"{base_id}-{suffix}"
        suffix += 1
    return printer_id


def persist_printers(printers):
    try:
        save_printers(printers)
    except OSError as exc:
        app.logger.exception("Could not save printer configuration")
        return jsonify({"error": f"Could not save printers.json: {exc}"}), 500
    return None

@app.route("/")
def index():
    global PRINTERS
    PRINTERS = load_printers()
    return render_template("index.html", printers=PRINTERS)


@app.route("/api/printers", methods=["POST"])
def api_add_printer():
    global PRINTERS
    PRINTERS = load_printers()
    printer, error = validate_printer_payload(request.get_json(silent=True))
    if error:
        return jsonify({"error": error}), 400
    printer["id"] = unique_printer_id(printer["name"], {p["id"] for p in PRINTERS})
    PRINTERS.append(printer)
    failure = persist_printers(PRINTERS)
    if failure:
        return failure
    return jsonify({"success": True, "printer": {k: v for k, v in printer.items() if k not in ("serial", "check_code")}}), 201


@app.route("/api/printers/<printer_id>", methods=["GET", "PUT", "DELETE"])
def api_printer(printer_id):
    global PRINTERS
    PRINTERS = load_printers()
    index = next((i for i, p in enumerate(PRINTERS) if p.get("id") == printer_id), None)
    if index is None:
        return jsonify({"error": "Printer not found"}), 404
    if request.method == "GET":
        return jsonify(PRINTERS[index])
    if request.method == "DELETE":
        del PRINTERS[index]
        failure = persist_printers(PRINTERS)
        if failure:
            return failure
        return jsonify({"success": True})

    printer, error = validate_printer_payload(request.get_json(silent=True))
    if error:
        return jsonify({"error": error}), 400
    printer["id"] = printer_id
    PRINTERS[index] = printer
    failure = persist_printers(PRINTERS)
    if failure:
        return failure
    return jsonify({"success": True})


@app.route("/api/printers/test", methods=["POST"])
def api_test_printer():
    printer, error = validate_printer_payload(request.get_json(silent=True))
    if error:
        return jsonify({"success": False, "error": error}), 400
    printer["id"] = "connection-test"
    result = run_async(query_printer(printer, load_thumbnail=False))
    if result["online"]:
        return jsonify({"success": True, "message": "Connection successful. The printer is reachable."})
    return jsonify({"success": False, "message": result.get("error") or "The printer did not respond. Check its network and credentials."})


@app.route("/api/printers/export", methods=["GET"])
def api_export_printers():
    response = jsonify(load_printers())
    response.headers["Content-Disposition"] = 'attachment; filename="flashforge-printers.json"'
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/printers/import", methods=["POST"])
def api_import_printers():
    global PRINTERS
    data = request.get_json(silent=True)
    if not isinstance(data, list) or len(data) > 100:
        return jsonify({"error": "Import must be a JSON array with no more than 100 printers"}), 400
    imported = []
    used_ids = set()
    for item in data:
        printer, error = validate_printer_payload(item)
        if error:
            return jsonify({"error": f"Invalid printer in import: {error}"}), 400
        requested_id = item.get("id", "")
        if isinstance(requested_id, str) and re.fullmatch(r"[a-z0-9_-]{1,80}", requested_id) and requested_id not in used_ids:
            printer_id = requested_id
        else:
            printer_id = unique_printer_id(printer["name"], used_ids)
        printer["id"] = printer_id
        used_ids.add(printer_id)
        imported.append(printer)
    PRINTERS = imported
    failure = persist_printers(PRINTERS)
    if failure:
        return failure
    return jsonify({"success": True, "count": len(PRINTERS)})


@app.route("/api/printers/order", methods=["PUT"])
def api_reorder_printers():
    global PRINTERS
    PRINTERS = load_printers()
    data = request.get_json(silent=True)
    ids = data.get("ids") if isinstance(data, dict) else None
    if (not isinstance(ids, list) or any(not isinstance(item, str) for item in ids)
            or len(ids) != len(PRINTERS) or set(ids) != {p["id"] for p in PRINTERS}):
        return jsonify({"error": "Order must include each configured printer ID exactly once"}), 400
    printer_by_id = {p["id"]: p for p in PRINTERS}
    PRINTERS = [printer_by_id[printer_id] for printer_id in ids]
    failure = persist_printers(PRINTERS)
    if failure:
        return failure
    return jsonify({"success": True})


@app.route("/api/status")
def api_status():
    results = run_async(all_printers())
    return jsonify(list(results))


@app.route("/api/led/<printer_id>", methods=["POST"])
def api_led(printer_id):
    cfg = get_printer_cfg(printer_id)
    if not cfg:
        return jsonify({"success": False, "error": "Unknown printer"}), 404

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("on"), bool):
        return jsonify({"success": False, "error": "Expected JSON boolean field 'on'"}), 400
    turn_on = data["on"]
    result = run_async(set_led(cfg, turn_on))
    return jsonify(result)


@app.route("/api/debug")
def api_debug():
    results = run_async(all_printers())
    for r in results:
        r["thumbnail"] = "..." if r.get("thumbnail") else None
    return jsonify(list(results))


if __name__ == "__main__":
    print("FlashForge Monitor running at http://localhost:5000")
    app.run(debug=False, host="0.0.0.0", port=5000)
