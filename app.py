from flask import Flask, render_template, request, jsonify
import pandas as pd
import requests
from bs4 import BeautifulSoup
import json
import sqlite3
from io import BytesIO, StringIO
import os
import tempfile
from urllib.parse import urlparse
import re

try:
    from pbixray import PBIXRay
    PBIX_AVAILABLE = True
except ImportError:
    PBIX_AVAILABLE = False

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # Increased for PBIX files

def clean_df(df):
    """Clean dataframe for JSON response"""
    df = df.fillna('')
    # Convert to records, limit preview to 100 rows
    return df.head(100).to_dict(orient='records'), list(df.columns), len(df)

FOOTNOTE_RE = re.compile(r'\[(?:[a-z]{1,2} ?\d+|\d+|[a-z]{1,2}|note \d+|citation needed)\]', re.IGNORECASE)

def strip_footnotes(value):
    if isinstance(value, str):
        return FOOTNOTE_RE.sub('', value).strip()
    return value

def clean_html_table(df):
    """Tidy scraped HTML tables (Wikipedia-style)."""
    # Flatten multi-level headers
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [' '.join(dict.fromkeys(str(c) for c in col if not str(c).startswith('Unnamed'))) or str(col[-1])
                      for col in df.columns]
    # Strip footnote markers from column names and cells
    df.columns = [strip_footnotes(str(c)) for c in df.columns]
    df = df.map(strip_footnotes)
    # Drop fully empty 'Unnamed: N' columns
    empty_unnamed = [c for c in df.columns if str(c).startswith('Unnamed')
                     and df[c].replace('', pd.NA).isna().all()]
    df = df.drop(columns=empty_unnamed)
    # Drop description rows: every non-index cell (all but the first column) holds the same text
    if df.shape[1] > 2:
        def is_description(row):
            vals = row.iloc[1:].dropna().astype(str).str.strip()
            vals = vals[vals != '']
            return len(vals) >= 2 and vals.nunique() == 1
        df = df[~df.apply(is_description, axis=1)]
    # Drop rows that are completely empty
    df = df[~df.apply(lambda r: r.dropna().astype(str).str.strip().eq('').all(), axis=1)]
    return df.reset_index(drop=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'error': 'No URL provided'}), 400
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    try:
        headers = {
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            )
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'lxml')
        # Prefer real data tables (e.g. Wikipedia wikitable) over layout/nav tables
        tables = soup.find_all('table', class_='wikitable') or soup.find_all('table')
        result = {'tables': [], 'text_preview': soup.get_text()[:2000]}
        for i, table in enumerate(tables[:5]):  # Limit to 5 tables
            try:
                # pandas 3+ treats a bare HTML string as a filesystem path
                df = pd.read_html(StringIO(str(table)))[0]
                df = clean_html_table(df)
                records, cols, total = clean_df(df)
                result['tables'].append({
                    'index': i,
                    'columns': cols,
                    'data': records,
                    'total_rows': total
                })
            except Exception:
                continue
        if not result['tables']:
            # Fallback: extract all text in structured way or lists
            result['message'] = 'No tables found. Showing text preview. Try AI extract for structured data.'
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    ext = os.path.splitext(file.filename)[1].lower()
    try:
        content = file.read()
        if ext in ['.csv', '.tsv']:
            sep = '\t' if ext == '.tsv' else ','
            df = pd.read_csv(BytesIO(content), sep=sep)
            records, cols, total = clean_df(df)
            return jsonify({'type': 'tabular', 'columns': cols, 'data': records, 'total_rows': total, 'sheets': None})
        elif ext in ['.xls', '.xlsx', '.xlsm']:
            xl = pd.ExcelFile(BytesIO(content))
            sheets = {}
            for sheet in xl.sheet_names[:3]:  # Limit sheets
                df = pd.read_excel(xl, sheet_name=sheet)
                records, cols, total = clean_df(df)
                sheets[sheet] = {'columns': cols, 'data': records, 'total_rows': total}
            return jsonify({'type': 'excel', 'sheets': sheets})
        elif ext == '.json':
            data = json.loads(content.decode('utf-8'))
            if isinstance(data, list) and data and isinstance(data[0], dict):
                df = pd.DataFrame(data)
                records, cols, total = clean_df(df)
                return jsonify({'type': 'tabular', 'columns': cols, 'data': records, 'total_rows': total})
            else:
                return jsonify({'type': 'json', 'raw': data if len(str(data)) < 10000 else str(data)[:5000]})
        elif ext in ['.pbix', '.pbit']:
            if not PBIX_AVAILABLE:
                return jsonify({'error': 'pbixray not installed. Run: pip install pbixray'}), 500
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            try:
                model = PBIXRay(tmp_path)
                tables_list = list(model.tables) if hasattr(model, 'tables') else []
                result = {'type': 'pbix', 'tables': {}, 'metadata': {}}
                # Extract up to 5 tables (limit for web response size)
                for tbl in tables_list[:5]:
                    try:
                        df = model.get_table(tbl)
                        if df is not None and not df.empty:
                            records, cols, total = clean_df(df)
                            result['tables'][tbl] = {
                                'columns': cols,
                                'data': records,
                                'total_rows': total
                            }
                    except Exception as e:
                        result['tables'][tbl] = {'error': str(e)}
                # Optional metadata
                try:
                    if hasattr(model, 'dax_measures') and model.dax_measures is not None:
                        result['metadata']['measures_count'] = len(model.dax_measures)
                    if hasattr(model, 'relationships') and model.relationships is not None:
                        result['metadata']['relationships_count'] = len(model.relationships)
                except Exception:
                    pass
                return jsonify(result)
            finally:
                os.unlink(tmp_path)
        elif ext in ['.db', '.sqlite', '.sqlite3']:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.db') as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            conn = sqlite3.connect(tmp_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in cursor.fetchall()]
            result = {'type': 'db', 'tables': {}}
            for tbl in tables[:5]:
                df = pd.read_sql_query(f"SELECT * FROM [{tbl}] LIMIT 100", conn)
                records, cols, total = clean_df(df)
                # Get full count
                cursor.execute(f"SELECT COUNT(*) FROM [{tbl}]")
                full_count = cursor.fetchone()[0]
                result['tables'][tbl] = {'columns': cols, 'data': records, 'total_rows': full_count}
            conn.close()
            os.unlink(tmp_path)
            return jsonify(result)
        else:
            return jsonify({'error': f'Unsupported file type: {ext}'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/process', methods=['POST'])
def process():
    """Apply filters, column selection, row ranges, basic stats"""
    data = request.json
    records = data.get('data', [])
    selected_cols = data.get('columns', None)
    row_start = data.get('row_start', 0)
    row_end = data.get('row_end', None)
    user_query = data.get('query', '').lower()
    if not records:
        return jsonify({'error': 'No data'}), 400
    df = pd.DataFrame(records)
    if selected_cols:
        df = df[[c for c in selected_cols if c in df.columns]]
    if row_end is not None:
        df = df.iloc[row_start:row_end]
    else:
        df = df.iloc[row_start:]
    # Intelligent suggestions based on query
    insights = {}
    numeric_cols = df.select_dtypes(include='number').columns.tolist()
    if numeric_cols:
        insights['stats'] = df[numeric_cols].describe().to_dict()
        insights['numeric_columns'] = numeric_cols
    insights['unique_counts'] = {col: int(df[col].nunique()) for col in df.columns}
    insights['missing'] = {col: int(df[col].isna().sum() or (df[col] == '').sum()) for col in df.columns}
    # Keyword matching for "cool data"
    suggestions = []
    if 'price' in user_query or 'cost' in user_query:
        suggestions.append('Detected possible price columns. Consider summing or averaging them.')
    if 'name' in user_query or 'title' in user_query:
        suggestions.append('Text columns can be used for uniqueness or frequency analysis.')
    if numeric_cols:
        suggestions.append(f'Numeric columns available for stats: {", ".join(numeric_cols)}')
    records_out = df.head(200).to_dict(orient='records')
    return jsonify({
        'data': records_out,
        'columns': list(df.columns),
        'total_filtered': len(df),
        'insights': insights,
        'suggestions': suggestions
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
