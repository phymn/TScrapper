# TScrapper

A Flask web app that pulls tables out of web pages (Wikipedia tables such as launch lists work especially well) and out of data files: CSV, TSV, Excel, JSON, SQLite and Power BI (`.pbix` / `.pbit`). You can pick columns and rows, see quick stats, optionally run a small AI model in the browser, and export the result as CSV, TSV, JSON, XLSX or XLS.

## Features
- **Web page tables**: fetches the page on the server, so browser CORS limits don't apply. It prefers real data tables (`table.wikitable`) over layout tables and reads up to 5 per page.
- **Wikipedia cleanup**: flattens multi-row headers, strips footnote markers such as `[1]`, `[a]`, `[note 3]` and `[citation needed]`, drops empty `Unnamed: N` columns, removes description rows that span the whole table, and removes blank rows.
- **File uploads**:
  - CSV and TSV
  - Excel `.xls`, `.xlsx` and `.xlsm` (first 3 sheets)
  - JSON (arrays of objects become tables)
  - SQLite `.db`, `.sqlite` and `.sqlite3` (first 5 tables, with full row counts)
  - Power BI `.pbix` and `.pbit` through [pbixray](https://github.com/Hugoberry/pbixray): up to 5 tables, plus how many DAX measures and relationships the model has
- **Filter and analyse**: choose columns, set a row range, and get stats on numeric columns, unique counts, missing values and keyword suggestions.
- **Optional AI extraction in the browser**: uses SmolLM2-135M-Instruct (q4) through Transformers.js, on WebGPU or WASM. It downloads about 140 MB the first time. Your data is never sent to an AI service.
- **Export in the browser**: CSV, TSV, JSON, or XLSX/XLS through SheetJS.

## Run it
```bash
pip install -r requirements.txt
python app.py
# open http://localhost:5000
```
`pbixray` is optional. Without it, everything works except Power BI uploads.

### On an iPhone (iSH)
This is possible but slow. iSH emulates x86, so building pandas and lxml there takes a long time. Try `apk add python3 py3-pip py3-pandas py3-lxml py3-openpyxl`, then `pip install flask requests beautifulsoup4 sqlalchemy`, then `python3 app.py`, and open `http://127.0.0.1:5000` in Safari. It runs much better on a Mac or PC.

## Files
| Path | Role |
|---|---|
| `app.py` | Flask server: the `/`, `/scrape`, `/upload` and `/process` routes, plus table cleanup |
| `templates/index.html` | Single-page UI (Tailwind CDN, SheetJS, Transformers.js) |
| `requirements.txt` | Python dependencies |
| `docs/HOW-IT-WORKS.md` | Detailed technical write-up |

## Limitations
- It doesn't run JavaScript, so pages that build their tables in the browser show no tables.
- Previews are capped: 100 rows per table, 200 rows after processing, 5 tables per page, file or database, and 3 Excel sheets.
- The AI model is very small, so treat its output as a draft.
- `app.run(debug=True, host='0.0.0.0')` starts the Werkzeug debugger and listens on every network interface. Only use it on a trusted network, and switch it to `debug=False` / `127.0.0.1` before sharing it.
- Follow each site's terms and robots.txt. This app is for personal and research use.

## License and credits
- Recommended license for the original code: MIT. No LICENSE file has been added yet.
- Third-party libraries: Flask (BSD-3), pandas (BSD-3), BeautifulSoup (MIT), lxml (BSD), requests (Apache-2.0), openpyxl (MIT), SQLAlchemy (MIT), pbixray (MIT), and in the browser Tailwind CSS (MIT), SheetJS Community Edition (Apache-2.0) and Transformers.js (Apache-2.0). SmolLM2 is Apache-2.0.

Author: Jesus Teran ([@phymn](https://github.com/phymn))
