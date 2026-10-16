"""
FlashForge printer dashboard.

Install:
    python -m pip install -r requirements.txt

Configure printer IP, serial and check code below, then run:
    python server.py

Open http://127.0.0.1:5000
"""

import asyncio
import base64
import math
import os
from datetime import timedelta

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# Fill these in for each printer. Keep credentials private; do not commit them.
PRINTERS = [
    {
        "id": "ad5x",
        "name": "AD5X",
        "ip": os.getenv("AD5X_IP", "FILL IN HERE"),
        "serial": os.getenv("AD5X_SERIAL", "FILL IN HERE"),
        "check_code": os.getenv("AD5X_CHECK_CODE", "FILL IN HERE"),
        "camera_url": os.getenv("AD5X_CAMERA_URL", "FILL IN HERE"),
    },
    {
        "id": "ad5m",
        "name": "AD5M",
        "ip": os.getenv("AD5M_IP", "FILL IN HERE"),
        "serial": os.getenv("AD5M_SERIAL", "FILL IN HERE"),
        "check_code": os.getenv("AD5M_CHECK_CODE", "FILL IN HERE"),
        "camera_url": os.getenv("AD5M_CAMERA_URL", "FILL IN HERE"),
    },
]

CONNECTION_OPTIONS = None


def get_printer_cfg(printer_id):
    return next((printer for printer in PRINTERS if printer["id"] == printer_id), None)


def seconds_to_time(seconds):
    """Convert a non-negative number of seconds to H:MM:SS."""
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def normalize_progress(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(value):
        return 0.0
    if 0 <= value <= 1:
        value *= 100
    return round(min(100.0, max(0.0, value)), 1)


def printer_result(cfg):
    return {
        "id": cfg["id"],
        "name": cfg["name"],
        "ip": cfg["ip"],
        "camera_url": cfg.get("camera_url") or None,
        "online": False,
        "error": None,
        "state": "unknown",
        "file": None,
        "progress": 0.0,
        "layer_current": None,
        "layer_total": None,
        "time_remaining": None,
        "time_elapsed": None,
        "temp_nozzle": None,
        "temp_nozzle_target": None,
        "temp_bed": None,
        "temp_bed_target": None,
        "thumbnail": None,
        "lights_on": None,
    }


def read_attr(obj, name, default=None):
    return getattr(obj, name, default) if obj is not None else default


async def query_printer(cfg):
    result = printer_result(cfg)

    missing = [key for key in ("ip", "serial", "check_code") if not cfg.get(key)]
    if missing:
        result["error"] = "Configure " + ", ".join(missing) + " for this printer."
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
                result["error"] = "Connection failed. Check the printer network and credentials."
                return result

            result["online"] = True
            info = await client.get_printer_status()
            if info:
                state = read_attr(info, "machine_state")
                result["state"] = getattr(state, "value", state) or "unknown"
                result["file"] = read_attr(info, "print_file_name")
                result["progress"] = normalize_progress(read_attr(info, "print_progress"))
                result["layer_current"] = read_attr(info, "current_print_layer")
                result["layer_total"] = read_attr(info, "total_print_layers")
                result["lights_on"] = read_attr(info, "lights_on")

                elapsed = read_attr(info, "print_duration")
                result["time_elapsed"] = seconds_to_time(elapsed)
                progress = result["progress"]
                try:
                    elapsed_num = float(elapsed)
                except (TypeError, ValueError):
                    elapsed_num = 0
                if elapsed_num > 0 and 0 < progress < 100:
                    result["time_remaining"] = seconds_to_time(
                        elapsed_num * (100 - progress) / progress
                    )

                extruder = read_attr(info, "extruder")
                bed = read_attr(info, "print_bed")
                if extruder:
                    result["temp_nozzle"] = read_attr(extruder, "current")
                    result["temp_nozzle_target"] = read_attr(extruder, "set")
                if bed:
                    result["temp_bed"] = read_attr(bed, "current")
                    result["temp_bed_target"] = read_attr(bed, "set")

            if result["file"]:
                try:
                    thumb_bytes = await client.files.get_gcode_thumbnail(result["file"])
                    if thumb_bytes:
                        encoded = base64.b64encode(thumb_bytes).decode("ascii")
                        result["thumbnail"] = f"data:image/png;base64,{encoded}"
                except Exception:
                    pass

                if not result["thumbnail"]:
                    try:
                        thumb_info = await client.tcp_client.get_thumbnail(result["file"])
                        if thumb_info and hasattr(thumb_info, "to_base64_data_url"):
                            result["thumbnail"] = thumb_info.to_base64_data_url()
                        elif thumb_info and hasattr(thumb_info, "get_image_bytes"):
                            image_bytes = thumb_info.get_image_bytes()
                            if image_bytes:
                                encoded = base64.b64encode(image_bytes).decode("ascii")
                                result["thumbnail"] = f"data:image/png;base64,{encoded}"
                    except Exception:
                        pass

            if result["temp_nozzle"] is None:
                try:
                    temperatures = await client.get_temperatures()
                    if temperatures:
                        extruder = (
                            temperatures.get_extruder_temp()
                            if hasattr(temperatures, "get_extruder_temp")
                            else None
                        )
                        bed = (
                            temperatures.get_bed_temp()
                            if hasattr(temperatures, "get_bed_temp")
                            else None
                        )
                        if extruder:
                            result["temp_nozzle"] = read_attr(extruder, "current")
                            result["temp_nozzle_target"] = read_attr(extruder, "set")
                        if bed:
                            result["temp_bed"] = read_attr(bed, "current")
                            result["temp_bed_target"] = read_attr(bed, "set")
                except Exception:
                    pass

    except ImportError:
        result["error"] = "Missing dependency. Install requirements.txt first."
    except (ConnectionRefusedError, OSError) as exc:
        result["error"] = f"Cannot reach printer at {cfg['ip']}: {exc}"
    except TimeoutError:
        result["error"] = f"Connection to {cfg['ip']} timed out."
    except Exception as exc:
        # Keep the server running if one printer or one API call fails.
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result


async def all_printers():
    return await asyncio.gather(*(query_printer(cfg) for cfg in PRINTERS))


async def set_led(cfg, turn_on):
    missing = [key for key in ("ip", "serial", "check_code") if not cfg.get(key)]
    if missing:
        return {"success": False, "error": "Configure " + ", ".join(missing) + "."}

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
                return {"success": False, "error": "Connection failed."}
            if turn_on:
                success = await client.control.set_led_on()
            else:
                success = await client.control.set_led_off()
            return {"success": bool(success), "lights_on": bool(turn_on) if success else None}
    except ImportError:
        return {"success": False, "error": "Missing dependency. Install requirements.txt first."}
    except Exception as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


@app.get("/")
def index():
    public_printers = [
        {
            "id": printer["id"],
            "name": printer["name"],
            "ip": printer["ip"],
            "camera_url": printer.get("camera_url") or None,
        }
        for printer in PRINTERS
    ]
    return render_template("index.html", printers=public_printers)


@app.get("/api/status")
def api_status():
    try:
        return jsonify(asyncio.run(all_printers()))
    except Exception:
        app.logger.exception("Failed to collect printer status")
        return jsonify({"error": "Unable to collect printer status."}), 500


@app.post("/api/led/<printer_id>")
def api_led(printer_id):
    cfg = get_printer_cfg(printer_id)
    if cfg is None:
        return jsonify({"success": False, "error": "Unknown printer."}), 404

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("on"), bool):
        return jsonify({"success": False, "error": 'Expected JSON body: {"on": true|false}'}), 400

    return jsonify(asyncio.run(set_led(cfg, data["on"])))


@app.get("/api/debug")
def api_debug():
    """Status without large thumbnail payloads."""
    results = asyncio.run(all_printers())
    for result in results:
        result["thumbnail"] = bool(result.get("thumbnail"))
    return jsonify(results)


if __name__ == "__main__":
    print("FlashForge Dashboard: http://127.0.0.1:5000")
    # Local network access is available; use a firewall if this host is exposed.
    app.run(debug=False, host="0.0.0.0", port=5000)
