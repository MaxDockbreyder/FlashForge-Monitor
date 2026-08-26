"""
FlashForge Dashboard - Backend
==============================
Installation:
    pip install flashforge-python-api flask

Start:
    python server.py

Then open in browser:
    http://localhost:5000
"""

import asyncio
import base64
from datetime import timedelta
from flask import Flask, render_template, jsonify

app = Flask(__name__)

# ─── CONFIGURATION ────────────────────────────────────────────────────────────
PRINTERS = [
    {
        "id":         "ad5x",
        "name":       "AD5X",
        "ip":         "192.168.1.100",   # ← adjust IP
        "serial":     "SNXXXXXXXXXX",    # ← enter serial number
        "check_code": "XXXXXXXX",        # ← enter check code / printer ID
        "camera_url": "http://XXXXXXXXXXXXXX:8080/?action=stream", # ← replace "X" with printer IP
    },
    {
        "id":         "ad5m",
        "name":       "AD5M",
        "ip":         "192.168.1.101",   # ← adjust IP
        "serial":     "SNXXXXXXXXXX",    # ← enter serial number
        "check_code": "XXXXXXXX",        # ← enter check code / printer ID
        "camera_url": "http://XXXXXXXXXXXX:8080/?action=stream", # ← replace "X" with printer IP
    },
]
# ──────────────────────────────────────────────────────────────────────────────


def seconds_to_time(seconds):
    if seconds is None or seconds <= 0:
        return None
    return str(timedelta(seconds=int(seconds)))


def normalize_progress(value):
    """Converts progress to 0-100%, regardless of whether API returns 0-1 or 0-100."""
    if value is None:
        return 0.0
    f = float(value)
    if f <= 1.0:
        return round(f * 100, 1)
    return round(f, 1)


async def query_printer(cfg):
    result = {
        "id":                 cfg["id"],
        "name":               cfg["name"],
        "ip":                 cfg["ip"],
        "camera_url":         cfg.get("camera_url", None),
        "online":             False,
        "error":              None,
        "state":              "unknown",
        "file":               None,
        "progress":           0.0,
        "layer_current":      None,
        "layer_total":        None,
        "time_remaining":     None,
        "time_elapsed":       None,
        "temp_nozzle":        None,
        "temp_nozzle_target": None,
        "temp_bed":           None,
        "temp_bed_target":    None,
        "thumbnail":          None,
        "_raw_progress":      None,
    }

    try:
        from flashforge import FlashForgeClient
        from flashforge.client import FiveMClientConnectionOptions

        options = FiveMClientConnectionOptions(http_port=8898, tcp_port=8899)
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
                result["_raw_progress"] = raw_prog
                result["progress"]      = normalize_progress(raw_prog)
                result["layer_current"] = getattr(info, "current_print_layer", None)
                result["layer_total"]   = getattr(info, "total_print_layers", None)

                elapsed_sec = getattr(info, "print_duration", None)
                result["time_elapsed"]  = seconds_to_time(elapsed_sec)

                prog_pct = result["progress"]
                if elapsed_sec and elapsed_sec > 0 and prog_pct and prog_pct > 0:
                    remaining = (elapsed_sec / prog_pct) * (100 - prog_pct)
                    result["time_remaining"] = seconds_to_time(int(remaining))

                extruder = getattr(info, "extruder", None)
                bed      = getattr(info, "print_bed", None)
                if extruder:
                    result["temp_nozzle"]        = getattr(extruder, "current", None)
                    result["temp_nozzle_target"] = getattr(extruder, "set", None)
                if bed:
                    result["temp_bed"]        = getattr(bed, "current", None)
                    result["temp_bed_target"] = getattr(bed, "set", None)

            # Load thumbnail
            if result["file"]:
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
            if result["temp_nozzle"] is None:
                try:
                    temp = await client.get_temperatures()
                    if temp:
                        ext  = temp.get_extruder_temp() if hasattr(temp, "get_extruder_temp") else None
                        bed  = temp.get_bed_temp()      if hasattr(temp, "get_bed_temp")      else None
                        if ext:
                            result["temp_nozzle"]        = getattr(ext, "current", None)
                            result["temp_nozzle_target"] = getattr(ext, "set", None)
                        if bed:
                            result["temp_bed"]        = getattr(bed, "current", None)
                            result["temp_bed_target"] = getattr(bed, "set", None)
                except Exception:
                    pass

    except ImportError:
        result["error"] = "flashforge-python-api not installed"
    except ConnectionRefusedError:
        result["error"] = f"Unreachable ({cfg['ip']})"
    except TimeoutError:
        result["error"] = f"Timeout ({cfg['ip']})"
    except Exception as e:
        result["error"] = str(e)

    return result


async def all_printers():
    tasks = [query_printer(cfg) for cfg in PRINTERS]
    return await asyncio.gather(*tasks)


@app.route("/")
def index():
    return render_template("index.html", printers=PRINTERS)


@app.route("/api/status")
def api_status():
    results = asyncio.run(all_printers())
    return jsonify(list(results))


@app.route("/api/debug")
def api_debug():
    results = asyncio.run(all_printers())
    for r in results:
        r["thumbnail"] = "..." if r.get("thumbnail") else None
    return jsonify(list(results))


if __name__ == "__main__":
    print("FlashForge Dashboard running at http://localhost:5000")
    print("Debug info:        http://localhost:5000/api/debug")
    app.run(debug=False, host="0.0.0.0", port=5000)
