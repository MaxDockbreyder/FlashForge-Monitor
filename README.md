# FlashForge Monitor 🖨

A real-time web dashboard for monitoring FlashForge AD5X and AD5M 3D printers on your local network.

![Dashboard Preview](https://img.shields.io/badge/status-active-brightgreen) ![Python](https://img.shields.io/badge/python-3.8%2B-blue) ![Flask](https://img.shields.io/badge/flask-3.x-lightgrey)

## Features

- 📊 Live print progress with animated progress bar
- 🖼️ Model thumbnail preview (if embedded in G-code)
- 🌡️ Nozzle and bed temperatures (current & target)
- ⏱️ Elapsed and estimated remaining print time
- 🔢 Current layer / total layers
- 🟢 Printer status badge (Printing / Ready / Paused / Error / Offline)
- 🔄 Auto-refresh every 30 seconds
- 📱 Responsive layout for desktop and mobile

## Requirements

- Python 3.8+
- FlashForge AD5X and/or AD5M connected to your local network
- Printer serial number and check code (Printer ID)

## Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/MaxDockbr/FlashForge-Monitor.git
   cd flashforge-monitor
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure your printers** in `server.py`
   ```python
   PRINTERS = [
       {
           "id":         "ad5x",
           "name":       "AD5X",
           "ip":         "192.168.1.100",   # Your printer's IP address
           "serial":     "SNXXXXXXXXXX",    # Serial number
           "check_code": "XXXXXXXX",        # Printer ID (8 digits, found on display)
       },
       ...
   ]
   ```

4. **Run the server**
   ```bash
   python server.py
   ```

5. **Open your browser** at [http://localhost:5000](http://localhost:5000)

## Finding Your Printer Credentials

| Field | Where to find it |
|-------|-----------------|
| **IP address** | Router admin page, or printer display → Settings → Network |
| **Serial number** | Printer display → Settings → Device Info |
| **Check code / Printer ID** | Printer display → Settings → Device Info (8-digit number) |

Alternatively, all three values are visible in the **Flash Studio** app under printer details.

## Project Structure

```
flashforge-monitor/
├── server.py              # Flask backend — printer polling & API
├── requirements.txt       # Python dependencies
├── templates/
│   └── index.html         # Frontend dashboard
├── static/                # Static assets (if any)
├── .gitignore
└── README.md
```

## Debug Endpoint

To inspect the raw data returned by your printers, open:

```
http://localhost:5000/api/debug
```

This shows all fields including the raw progress value from the API.

## How Remaining Time Is Calculated

The FlashForge API does not expose remaining print time directly. The dashboard estimates it using:

```
remaining = (elapsed / progress%) × (100% - progress%)
```

The estimate becomes more accurate as the print progresses.

## Supported Printers

| Printer | Tested |
|---------|--------|
| FlashForge AD5M | ✅ |
| FlashForge AD5X | ✅ |
| Other FlashForge 5M series | Should work |

## Contributing

Pull requests are welcome! If you have a different FlashForge model and it works (or doesn't), feel free to open an issue.

## License

MIT License — see [LICENSE](LICENSE) for details.
