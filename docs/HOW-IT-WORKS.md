# TScrapper: How it works

## 1. What it does
TScrapper turns web tables and data files into clean tables you can filter and export. It has two layers:
- **Server** (`app.py`, Flask): fetches web pages, parses tables, reads uploaded files, and works out basic stats.
- **Browser** (`templates/index.html`): shows the controls and previews, runs the optional on-device AI step, and builds the export files.

```
Browser UI ──POST /scrape {url}────────► requests.get → BeautifulSoup → pd.read_html → clean_html_table → clean_df ─┐
           ──POST /upload (multipart)──► by file extension: CSV/TSV | Excel | JSON | SQLite | PBIX → clean_df ────────┤
           ◄────────────── JSON {tables / sheets, columns, data (≤100 rows), total_rows} ◄──────────────────────────┘
           ──POST /process {data, columns, row_start, row_end, query}──► column/row filter + describe() + suggestions
           ◄────────────── JSON {data (≤200 rows), insights, suggestions}
Browser: optional Transformers.js SmolLM2 extraction → export (CSV/TSV/JSON by Blob, XLSX/XLS by SheetJS)
```

## 2. Files
| File | Role |
|---|---|
| `app.py` | Every server route and the cleanup helpers |
| `templates/index.html` | UI, client state (`currentData`, `currentColumns`), AI extraction, export |
| `requirements.txt` | flask, pandas, openpyxl, requests, beautifulsoup4, lxml, sqlalchemy, pbixray |

## 3. Server (`app.py`)
### Configuration
- `MAX_CONTENT_LENGTH = 100 MB`, so large `.pbix` files can be uploaded.
- `pbixray` is imported inside `try/except`. When it's missing, `PBIX_AVAILABLE=False` and `.pbix` uploads return a 500 error that tells you how to install it.

### Helpers
- `clean_df(df)`: fills NaN with `''` and returns `(first 100 rows as records, column list, total row count)`. Every route uses it, so the JSON stays small.
- `FOOTNOTE_RE`: `\[(?:[a-z]{1,2} ?\d+|\d+|[a-z]{1,2}|note \d+|citation needed)\]`, case-insensitive. It matches Wikipedia reference markers such as `[1]`, `[a]`, `[nb 2]`, `[note 3]` and `[citation needed]`.
- `strip_footnotes(v)`: applies that regex to strings and leaves other values alone.
- `clean_html_table(df)` makes these passes, in order:
  1. **MultiIndex headers**: joins the header levels, drops `Unnamed…` levels and removes duplicate parts while keeping their order (`dict.fromkeys`). If nothing is left, it falls back to the last level.
  2. **Footnotes**: strips them from column names and from every cell (`DataFrame.map`).
  3. **Empty `Unnamed: N` columns**: drops them when every value is empty or NaN.
  4. **Description rows** (only for tables with more than 2 columns): drops a row when at least 2 non-empty cells after the first column all hold the same text. Wikipedia launch lists use one spanning cell like this to describe the launch below it, and `read_html` copies that text into every column.
  5. **Blank rows**: drops rows where every cell is empty.
  6. Resets the index.

### Routes
| Route | Input | What it does |
|---|---|---|
| `GET /` | | Serves `index.html` |
| `POST /scrape` | JSON `{url}` | Adds `https://` if no scheme is given. Fetches the page with a desktop Chrome User-Agent and a 15 s timeout, and fails on HTTP errors. Parses it with `lxml`, takes `table.wikitable` or else every `<table>`, and handles the first 5. Each table goes through `pd.read_html(StringIO(html))`. The `StringIO` is needed because pandas 3 would otherwise treat the string as a file path. Then it runs `clean_html_table` and `clean_df`. A table that fails to parse is skipped. It also returns `text_preview`, the first 2000 characters of the page text, and a message when no tables were found. |
| `POST /upload` | multipart `file` | Chooses a parser by extension. **CSV/TSV**: `read_csv`. **XLS/XLSX/XLSM**: `ExcelFile`, first 3 sheets. **JSON**: a list of objects becomes a DataFrame; anything else is returned raw, cut down if it's longer than 10k characters. **PBIX/PBIT**: writes a temp file, then `PBIXRay(path)`, `model.tables`, and `get_table()` for the first 5; it adds `measures_count` and `relationships_count` when they're available, and always deletes the temp file. **SQLite**: writes a temp file, lists tables from `sqlite_master`, runs `SELECT * … LIMIT 100` on the first 5 plus `COUNT(*)` for the real total, then deletes the temp file. |
| `POST /process` | JSON `{data, columns, row_start, row_end, query}` | Rebuilds a DataFrame from the preview records, keeps the chosen columns (ignoring any that don't exist) and slices the rows. **Insights**: `describe()` on numeric columns, `nunique` for each column, and missing counts (NaN, or else empty strings). **Suggestions**: keywords in the query (`price/cost`, `name/title`) plus a list of the numeric columns. Returns up to 200 rows. |

## 4. Client (`templates/index.html`)
- `scrapeUrl()` and `uploadFile()` call the server, then `showTables()` shows a selector when there are several tables, sheets or database tables, and `selectTable(i)` / `showPreview()` / `renderTable()` draw the preview and the column checkboxes.
- `processData()` sends the current rows plus the selected columns, row range and query to `/process`. `showInsights()` displays the results.
- `aiExtract()` lazily imports `@huggingface/transformers@3.1.2` from jsDelivr and builds a `text-generation` pipeline with `HuggingFaceTB/SmolLM2-135M-Instruct` (`dtype:'q4'`), using WebGPU when the browser has it and WASM otherwise. The prompt contains the user's request and the first 30 rows as JSON. Settings are `max_new_tokens:512` and `temperature:0.1`. The app pulls the first `[...]` block out of the answer and treats it as the new data. If anything fails, it falls back to `processData()`.
- `downloadData()`: CSV quotes each value and doubles any quotes inside it. TSV is plain. JSON is pretty-printed. XLSX/XLS go through `XLSX.utils.json_to_sheet` and `XLSX.writeFile` with the chosen `bookType`. The file is named `scraped_data.<ext>`.

## 5. Why these limits
The 100- and 200-row previews and the 5-table and 3-sheet caps keep the JSON small, so the phone or browser stays responsive. Export uses the current client data, which is the preview or processed rows, not the whole source. A 15 s timeout keeps a slow site from hanging the request.

## 6. Running and deploying
- On a desktop: `pip install -r requirements.txt && python app.py`, then open `http://localhost:5000`.
- On an iPhone in iSH: see the README. Install the pandas and lxml packages from Alpine, then run `python3 app.py` and open `http://127.0.0.1:5000`.
- In production: put it behind gunicorn or waitress and turn debug mode off.

## 7. Testing done
Testing was manual: Wikipedia launch-list pages (footnotes, multi-row headers, description rows), CSV and XLSX uploads, and exports in every format. A fix for pandas 3 `read_html` (the `StringIO` wrapper) is included. There are no automated tests yet.

## 8. Known limits and future work
- There's no JavaScript rendering. A Playwright option would cover dynamic sites.
- Export only covers the preview or processed rows. A future version could return a full-table download from the server.
- The SQL table names in the SQLite reader come from the uploaded file itself. They're bracket-quoted, but they shouldn't be exposed publicly as-is.
- `debug=True` / `0.0.0.0` should be made configurable through environment variables.
- Future ideas: pagination, multi-table merge, scheduled scrapes, and a local-LLM option (Ollama).
