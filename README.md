# FlashForge Monitor

A local web dashboard for monitoring FlashForge printers on your network. Configure printers in the dashboard; no edits to `server.py` are needed.

## Features

- Add printers from the **Add printer** form; configuration is saved in `printers.json` and loaded on startup.
- Edit or remove printers, and test their network connection before saving.
- Export and import a JSON backup of the printer list.
- Drag printer cards to reorder them; the order is saved automatically.
- Start with an empty printer list and add as many printers as needed.
- Responsive printer cards reflow automatically as the list grows.
- Live printer status, print progress, layer count, temperatures, elapsed and estimated remaining time.
- G-code thumbnail previews when available.
- Expandable MJPEG camera streams.
- Printer LED controls and a configurable 10, 30, or 60 second refresh interval.
- Clear status labels and actionable connection error messages.
- Input validation, unique printer IDs, and atomic JSON writes.

## Preview
<img width="1919" height="1079" alt="dashboard-preview" src="https://github.com/user-attachments/assets/5dd96edd-18a5-497b-a24c-f666316f83a4" />
<img width="1919" height="1079" alt="add-printer-preview" src="https://github.com/user-attachments/assets/7b97d736-f848-477a-8512-51decea51c6f" />



## Requirements

- Python 3.8 or newer
- FlashForge printer on the same local network with LAN Mode enabled
- Printer IP address, serial number, and LAN check code

## Setup

```bash
python -m venv .venv
```

Activate the virtual environment, then install dependencies and start the dashboard:

```bash
python -m pip install -r requirements.txt
python server.py
```

Open [http://localhost:5000](http://localhost:5000), choose **Add printer**, and enter the printer details. A camera URL is optional. The dashboard writes the configuration to `printers.json`, which is kept out of version control because it contains printer credentials.

Backups also contain printer credentials. Store exported backup files securely and do not commit them to GitHub.

Enable LAN Mode on the printer touchscreen under **Settings → Network → LAN Mode**. The serial number and check code are available in the printer's device information (the check code may only appear when LAN Mode is enabled). The printer IP can be found in network settings or your router.

## API endpoints

- `GET /api/status` — status for configured printers
- `POST /api/printers` — add a printer using JSON fields `name`, `ip`, `serial`, `check_code`, and optional `camera_url`
- `GET /api/printers/<printer_id>` — retrieve printer configuration for editing
- `PUT` or `DELETE /api/printers/<printer_id>` — update or remove a printer
- `POST /api/printers/test` — test printer connectivity without saving
- `GET /api/printers/export` and `POST /api/printers/import` — download or restore a JSON backup
- `PUT /api/printers/order` — save the dashboard order
- `POST /api/led/<printer_id>` — set the printer LED with `{"on": true}` or `{"on": false}`
- `GET /api/debug` — status diagnostics without thumbnail image data

## Troubleshooting

- **Connection failed/offline:** verify the IP, serial, check code, and LAN Mode.
- **Missing dependency:** install packages with `python -m pip install -r requirements.txt`.
- **Camera unavailable:** verify the optional stream URL in a browser.
- **Configuration won't save:** ensure the application directory is writable; check the server log for details.

## Project layout

```text
server.py              Flask backend and API
templates/index.html   Dashboard and add-printer form
printers.json          Local printer configuration (ignored by Git)
requirements.txt       Python dependencies
```

## License

MIT. See [LICENSE](LICENSE).
