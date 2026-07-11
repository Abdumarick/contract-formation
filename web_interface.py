from flask import Flask, render_template, request, jsonify, send_file
import os
import sys
import csv
import json
import re
import logging
import shutil
logging.basicConfig(level=logging.DEBUG)
from werkzeug.utils import secure_filename
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from main import parse_pdf

def normalise_date(s):
    """Accept DD/MM/YYYY or YYYY-MM-DD, return DD/MM/YYYY for CSV output."""
    s = (s or '').strip()
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', s)
    if m:
        return f"{int(m.group(1)):02d}/{int(m.group(2)):02d}/{m.group(3)}"
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', s)
    if m:
        return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
    return s


def safe_file_stem(value, fallback='contract'):
    """Return a Windows-safe filename stem without path separators."""
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', '_', (value or '').strip())
    stem = re.sub(r'\s+', '_', stem)
    stem = re.sub(r'_+', '_', stem).strip(' ._')
    return (stem or fallback)[:40]


# Base directory = folder containing web_interface.py (always absolute)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# HTML templates live in the templates/ subfolder.
app = Flask(__name__,
            template_folder=os.path.join(BASE_DIR, 'templates'),
            static_folder=BASE_DIR)
app.secret_key = 'hotel-contract-parser-secret-key'

UPLOAD_FOLDER  = os.path.join(BASE_DIR, 'uploads')
OUTPUT_FOLDER  = os.path.join(BASE_DIR, 'outputs')
ALLOWED_EXTENSIONS = {'pdf'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER']      = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER']      = OUTPUT_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ── CSV column order (matches CRM schema) ────────────────────────────────────
CSV_COLUMNS = [
    'location_name', 'hotel_name', 'hotel_group', 'hotel_desc',
    'inside_restricted_area', 'margin', 'ignore_proposal_margin',
    'currency', 'room_name', 'room_desc', 'max_cap',
    'min_age', 'max_age', 'min_pax', 'max_pax',
    'cost', 'single_supplement', 'hb_supplement', 'fb_supplement',
    'start_date', 'end_date',
]


# ─────────────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')


# ── PDF upload (original) ─────────────────────────────────────────────────────
@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file selected'}), 400

    file = request.files['file']
    if not file.filename or not allowed_file(file.filename):
        return jsonify({'error': 'Only PDF files are allowed'}), 400

    try:
        filename  = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filepath  = os.path.join(app.config['UPLOAD_FOLDER'], f'{timestamp}_{filename}')
        file.save(filepath)

        output_dir    = os.path.join(app.config['OUTPUT_FOLDER'], f'output_{timestamp}')
        year_override = request.form.get('year', '').strip() or None

        result = parse_pdf(pdf_path=filepath, output_dir=output_dir, year_override=year_override)

        # Reformat dates in the generated CSV to DD/MM/YYYY
        csv_path = result['csv']
        rows_data = []
        if os.path.exists(csv_path):
            with open(csv_path, newline='', encoding='utf-8') as f:
                rows_data = list(csv.DictReader(f))
            for row in rows_data:
                if row.get('start_date'): row['start_date'] = normalise_date(row['start_date'])
                if row.get('end_date'):   row['end_date']   = normalise_date(row['end_date'])
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                writer.writeheader()
                writer.writerows(rows_data)

        # Save metadata for contracts library
        first = rows_data[0] if rows_data else {}
        meta = {
            'source':       'pdf',
            'original_pdf': filename,
            'hotel_name':   first.get('hotel_name', ''),
            'hotel_group':  first.get('hotel_group', '') or 'Single',
            'location':     first.get('location_name', '') or '',
            'csv_file':     os.path.basename(csv_path),
            'xlsx_file':    os.path.basename(result['xlsx']) if result.get('xlsx') else None,
            'row_count':    len(rows_data),
            'created_at':   datetime.now().isoformat(),
            'output_dir':   f'output_{timestamp}',
        }
        with open(os.path.join(output_dir, 'meta.json'), 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2)

        return jsonify({
            'success':    True,
            'message':    'PDF processed successfully!',
            'csv_file':   os.path.basename(csv_path),
            'output_dir': f'output_{timestamp}',
            'excel_file': os.path.basename(result['xlsx']) if result.get('xlsx') else None,
        })
    except Exception as e:
        return jsonify({'error': f'Error processing PDF: {str(e)}'}), 500


@app.route('/manual', methods=['POST'])
def manual_entry():
    """
    Accepts JSON from the manual entry form (rate table design) and writes a CRM-ready CSV.

    Expected JSON shape:
    {
        hotel_name, contract_year, base_plan, hotel_desc, notes,
        season_rows:  [{sid, name}, ...],
        room_cols:    [{colId, name, max_cap, cost_basis}, ...],
        cost_matrix:  {sid: {colId: cost}, ...},
        date_ranges:  [{sid, start, end}, ...],
        age_bands:    [{label, min_age, max_age, discount, notes}, ...],
        hb_supplement, fb_supplement,
        meal_costs:   {breakfast, lunch, dinner},
        extra_supplements: [{name, amount, season}, ...],
    }

    Single supplement rule
    ----------------------
    cost_pp  = room_cost / max_cap          (always divide by capacity)
    sgl_supp = cost_pp                      (what one person pays per night)
    Applied to child and adult only; infant always 0.
    """
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({'error': 'No JSON data received'}), 400

        hotel_name  = data.get('hotel_name', '').strip()
        location_name = data.get('location_name', '').strip()
        hotel_desc  = data.get('hotel_desc', '')
        room_desc   = data.get('room_desc', '')
        inside_restricted_area = data.get('inside_restricted_area', 'FALSE') or 'FALSE'
        ignore_proposal_margin = data.get('ignore_proposal_margin', 'FALSE') or 'FALSE'
        season_rows = data.get('season_rows', [])   # [{sid, name}]
        room_cols   = data.get('room_cols',   [])   # [{colId, name, max_cap, cost_basis}]
        cost_matrix = data.get('cost_matrix', {})   # {sid: {colId: cost}}
        date_ranges = data.get('date_ranges', [])   # [{sid, start, end}]
        age_bands   = data.get('age_bands',   [])
        hb_global   = float(data.get('hb_supplement', 0))
        fb_global   = float(data.get('fb_supplement', 0))

        if not hotel_name:
            return jsonify({'error': 'hotel_name is required'}), 400
        if not season_rows:
            return jsonify({'error': 'Add at least one season row in the rate table'}), 400
        if not room_cols:
            return jsonify({'error': 'Add at least one room column in the rate table'}), 400
        if not date_ranges:
            return jsonify({'error': 'Add at least one date range'}), 400

        # sid → season name lookup
        season_name_map = {s['sid']: s['name'] for s in season_rows}
        app.logger.debug(f"[manual] season_name_map={season_name_map}")
        app.logger.debug(f"[manual] age_bands={age_bands}")
        app.logger.debug(f"[manual] extra_supplements={data.get('extra_supplements', [])}")

        # Use age bands exactly as entered — no auto-injection of infant or any preset
        if not age_bands:
            return jsonify({'error': 'Add at least one age band'}), 400

        rows = []
        for room in room_cols:
            room_name    = room.get('name', 'Room')
            max_cap      = max(int(room.get('max_cap', 1)), 1)
            basis        = room.get('cost_basis', 'per_room')
            col_id       = room.get('colId', '')
            sgl_override      = float(room.get('sgl_override', 0) or 0)
            sgl_override_type = room.get('sgl_override_type', 'usd')  # 'usd' | 'pct'

            for dr in date_ranges:
                sid        = dr.get('sid', '')
                start_date = normalise_date(dr.get('start', ''))
                end_date   = normalise_date(dr.get('end',   ''))

                raw_cost = float((cost_matrix.get(sid) or {}).get(col_id, 0) or 0)

                if basis == 'per_room':
                    cost_pp = round(raw_cost / max_cap, 2)
                else:
                    cost_pp = raw_cost

                # Single supplement base: respect unit type
                if sgl_override > 0:
                    if sgl_override_type == 'pct':
                        sgl_supp = round(cost_pp * sgl_override / 100.0, 2)
                    else:
                        sgl_supp = sgl_override
                else:
                    sgl_supp = cost_pp if max_cap > 1 else 0.0

                # Check if any extra supplement overrides single/hb/fb for this room
                def get_extra_override(otype, band_label, season_name='', band_min=None, band_max=None):
                    for xs in data.get('extra_supplements', []):
                        if xs.get('override_type') != otype: continue
                        xs_rooms = xs.get('rooms') or ([xs.get('room')] if xs.get('room') else [])
                        xs_bands = xs.get('bands') or ([xs.get('band')] if xs.get('band') else [])
                        xs_rooms = [r for r in xs_rooms if r]
                        xs_bands = [b for b in xs_bands if b]
                        if xs_rooms and room_name not in xs_rooms: continue
                        # Band matching: values look like "child_13_16"; empty list means all bands.
                        if xs_bands:
                            band_matches = False
                            for xs_band in xs_bands:
                                parts = xs_band.split('_')
                                band_type = parts[0]
                                if band_type != band_label:
                                    continue
                                if len(parts) >= 3 and band_min is not None and band_max is not None:
                                    try:
                                        if int(parts[1]) != band_min or int(parts[2]) != band_max:
                                            continue
                                    except (ValueError, IndexError):
                                        pass
                                band_matches = True
                                break
                            if not band_matches:
                                continue
                        season_amounts = xs.get('season_amounts', [])
                        if season_amounts:
                            match = next((sa for sa in season_amounts
                                          if sa.get('season','') == season_name), None)
                            app.logger.debug(
                                f"[override] type={otype} bands={xs_bands} "
                                f"band_label={band_label} min={band_min} max={band_max} "
                                f"season='{season_name}' match={match}"
                            )
                            if not match:
                                continue
                            amt      = float(match.get('amount', 0) or 0)
                            amt_type = match.get('amount_type', 'usd')
                        else:
                            continue
                        if amt_type == 'pct':
                            return round(cost_pp * amt / 100.0, 2)
                        return amt
                    return None

                for band in age_bands:
                    label         = band.get('label', 'adult')
                    min_age       = int(band.get('min_age', 0))
                    max_age       = int(band.get('max_age', 99))
                    discount      = float(band.get('discount', 100))
                    discount_type = band.get('discount_type', 'pct')
                    hbfb_mode     = band.get('hbfb_mode', 'apply_discount')
                    child_hb_amt  = float(band.get('child_hb', 0) or 0)
                    child_fb_amt  = float(band.get('child_fb', 0) or 0)

                    # Zero-cost bands still may carry HB/FB meal supplements.
                    if discount == 0:
                        row_cost = 0.0
                        row_sgl  = 0.0
                    else:
                        if discount_type == 'usd':
                            row_cost = round(float(discount), 2)
                        else:
                            row_cost = round(cost_pp * (discount / 100.0), 2)

                        # Cost override — replaces the base room rate for this band/room/season
                        cost_xs = get_extra_override('cost', label, season_name_map.get(sid,''), min_age, max_age)
                        if cost_xs is not None:
                            row_cost = cost_xs

                        sgl_xs  = get_extra_override('single_supp', label, season_name_map.get(sid,''), min_age, max_age)
                        row_sgl = sgl_xs if sgl_xs is not None else sgl_supp

                    if label in ('child', 'infant'):
                        if hbfb_mode == 'same_as_adult':
                            base_hb, base_fb = hb_global, fb_global
                        elif hbfb_mode == 'custom':
                            base_hb, base_fb = child_hb_amt, child_fb_amt
                        else:
                            f = (discount / 100.0) if discount_type == 'pct' else 1.0
                            base_hb = round(hb_global * f, 2)
                            base_fb = round(fb_global * f, 2)
                    else:
                        base_hb, base_fb = hb_global, fb_global

                    hb_xs  = get_extra_override('hb_supp', label, season_name_map.get(sid,''), min_age, max_age)
                    fb_xs  = get_extra_override('fb_supp', label, season_name_map.get(sid,''), min_age, max_age)
                    row_hb = hb_xs if hb_xs is not None else base_hb
                    row_fb = fb_xs if fb_xs is not None else base_fb

                    rows.append({
                        'location_name':          location_name,
                        'hotel_name':             hotel_name,
                        'hotel_group':            '',
                        'hotel_desc':             hotel_desc,
                        'inside_restricted_area': inside_restricted_area,
                        'margin':                 0,
                        'ignore_proposal_margin': ignore_proposal_margin,
                        'currency':               'USD',
                        'room_name':              room_name,
                        'room_desc':              room_desc,
                        'max_cap':                max_cap,
                        'min_age':                min_age,
                        'max_age':                max_age,
                        'min_pax':                1,
                        'max_pax':                max_cap,
                        'cost':                   row_cost,
                        'single_supplement':      row_sgl,
                        'hb_supplement':          row_hb,
                        'fb_supplement':          row_fb,
                        'start_date':             start_date,
                        'end_date':               end_date,
                    })

        # Write CSV
        timestamp  = datetime.now().strftime('%Y%m%d_%H%M%S')
        save_to_output_dir = (data.get('save_to_output_dir') or '').strip()
        if save_to_output_dir:
            if '/' in save_to_output_dir or '\\' in save_to_output_dir or '..' in save_to_output_dir:
                return jsonify({'error': 'Invalid saved contract folder'}), 400
            output_dir_name = save_to_output_dir
            output_dir = os.path.join(app.config['OUTPUT_FOLDER'], output_dir_name)
            if not os.path.isdir(output_dir):
                return jsonify({'error': 'Saved contract folder was not found'}), 404
            for old_file in os.listdir(output_dir):
                if old_file.lower().endswith('.csv'):
                    os.remove(os.path.join(output_dir, old_file))
        else:
            output_dir_name = f'manual_{timestamp}'
            output_dir = os.path.join(app.config['OUTPUT_FOLDER'], output_dir_name)
        os.makedirs(output_dir, exist_ok=True)

        safe_name = safe_file_stem(hotel_name)
        csv_file  = f'{safe_name}_{timestamp}.csv'
        csv_path  = os.path.join(output_dir, csv_file)

        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

        # Save metadata for contracts library
        meta = {
            'source':      'manual',
            'hotel_name':  hotel_name,
            'hotel_group': data.get('hotel_group', '') or 'Single',
            'location':    data.get('location_name', '') or '',
            'csv_file':    csv_file,
            'xlsx_file':   None,
            'row_count':   len(rows),
            'created_at':  datetime.now().isoformat(),
            'output_dir':  output_dir_name,
            'contract_year': data.get('contract_year', ''),
            'base_plan':   data.get('base_plan', ''),
        }
        with open(os.path.join(output_dir, 'meta.json'), 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2)

        # Save full form data for re-edit
        meta_path = os.path.join(output_dir, 'entry_data.json')
        saved_form_data = dict(data)
        saved_form_data.pop('save_to_output_dir', None)
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(saved_form_data, f, indent=2, ensure_ascii=False)

        return jsonify({
            'success':    True,
            'hotel_name': hotel_name,
            'row_count':  len(rows),
            'csv_file':   csv_file,
            'output_dir': output_dir_name,
        })

    except Exception as e:
        return jsonify({'error': f'Error generating CSV: {str(e)}'}), 500


# ── Parse PDF for manual form pre-fill ───────────────────────────────────────
@app.route('/parse_for_manual', methods=['POST'])
def parse_for_manual():
    """
    Parses a PDF and returns structured JSON to pre-populate the manual entry form.
    Does NOT write any CSV — just returns the extracted data for review.
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file selected'}), 400

    file = request.files['file']
    if not file.filename or not allowed_file(file.filename):
        return jsonify({'error': 'Only PDF files are allowed'}), 400

    try:
        from main import extract_for_manual

        filename  = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filepath  = os.path.join(app.config['UPLOAD_FOLDER'], f'manual_{timestamp}_{filename}')
        file.save(filepath)

        year_override = request.form.get('year', '').strip() or None
        data = extract_for_manual(filepath, year_override=year_override)

        return jsonify({'success': True, **data})

    except Exception as e:
        return jsonify({'error': f'Could not parse PDF: {str(e)}'}), 500


# ── File download ─────────────────────────────────────────────────────────────
@app.route('/download/<output_dir>/<filename>')
def download_file(output_dir, filename):
    try:
        file_path = os.path.join(app.config['OUTPUT_FOLDER'], output_dir, filename)
        return send_file(file_path, as_attachment=True)
    except Exception as e:
        return jsonify({'error': f'Error downloading file: {str(e)}'}), 500


# ── Logs ──────────────────────────────────────────────────────────────────────
@app.route('/logs/<output_dir>')
def view_logs(output_dir):
    try:
        if output_dir == 'latest':
            # Find most recent output folder
            dirs = sorted([
                d for d in os.listdir(app.config['OUTPUT_FOLDER'])
                if os.path.isdir(os.path.join(app.config['OUTPUT_FOLDER'], d))
            ], reverse=True)
            if not dirs:
                return jsonify({'text': 'No logs yet.'})
            output_dir = dirs[0]

        log_dir = os.path.join(app.config['OUTPUT_FOLDER'], output_dir, 'logs')
        logs    = {}

        json_path = os.path.join(log_dir, 'audit_log.json')
        if os.path.exists(json_path):
            with open(json_path, encoding='utf-8') as f:
                logs['json'] = json.load(f)

        txt_path = os.path.join(log_dir, 'audit_log.txt')
        if os.path.exists(txt_path):
            with open(txt_path, encoding='utf-8') as f:
                logs['text'] = f.read()

        if not logs:
            logs['text'] = 'No logs available for this run.'

        return jsonify(logs)
    except Exception as e:
        return jsonify({'error': f'Error reading logs: {str(e)}'}), 500



# ── Contracts Library ─────────────────────────────────────────────────────────
@app.route('/library')
def library():
    return render_template('library.html')


@app.route('/api/contracts')
def list_contracts():
    """Scan all output folders, read meta.json (or fall back to CSV first row)."""
    out_dir = app.config['OUTPUT_FOLDER']
    contracts = []
    try:
        dirs = sorted([
            d for d in os.listdir(out_dir)
            if os.path.isdir(os.path.join(out_dir, d))
        ], reverse=True)
    except FileNotFoundError:
        return jsonify([])

    for d in dirs:
        folder = os.path.join(out_dir, d)
        meta_file = os.path.join(folder, 'meta.json')

        if os.path.exists(meta_file):
            with open(meta_file, encoding='utf-8') as f:
                meta = json.load(f)
        else:
            # Legacy: read first row of any CSV in the folder
            csvs = [f for f in os.listdir(folder) if f.endswith('.csv')]
            if not csvs:
                continue
            csv_file = csvs[0]
            try:
                with open(os.path.join(folder, csv_file), newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    first  = next(reader, {})
                meta = {
                    'source':      'legacy',
                    'hotel_name':  first.get('hotel_name', d),
                    'hotel_group': first.get('hotel_group', '') or 'Single',
                    'location':    first.get('location_name', '') or '',
                    'csv_file':    csv_file,
                    'xlsx_file':   None,
                    'row_count':   None,
                    'created_at':  None,
                    'output_dir':  d,
                    'contract_year': '',
                    'base_plan':   '',
                }
            except Exception:
                continue

        # Find actual files on disk (in case they were renamed / added)
        files = os.listdir(folder)
        meta['output_dir'] = d
        meta['csv_file']   = next((f for f in files if f.endswith('.csv')), meta.get('csv_file'))
        meta['xlsx_file']  = next((f for f in files if f.endswith(('.xlsx','.xls'))), meta.get('xlsx_file'))
        meta['has_entry_data'] = os.path.exists(os.path.join(folder, 'entry_data.json'))

        # Derive timestamp label from folder name
        parts = d.replace('manual_','').replace('output_','')
        try:
            meta['created_at'] = meta.get('created_at') or \
                datetime.strptime(parts[:15], '%Y%m%d_%H%M%S').isoformat()
        except Exception:
            pass

        contracts.append(meta)

    return jsonify(contracts)


@app.route('/api/contracts/<output_dir>', methods=['DELETE'])
def delete_contract(output_dir):
    """Delete an entire output folder."""
    if '/' in output_dir or '\\' in output_dir or '..' in output_dir:
        return jsonify({'error': 'Invalid folder name'}), 400
    folder = os.path.join(app.config['OUTPUT_FOLDER'], output_dir)
    if not os.path.isdir(folder):
        return jsonify({'error': 'Folder not found'}), 404
    shutil.rmtree(folder)
    return jsonify({'success': True})


@app.route('/api/contracts/<output_dir>/entry_data')
def get_entry_data(output_dir):
    """Return the saved form JSON for re-loading into the manual entry form."""
    if '/' in output_dir or '..' in output_dir:
        return jsonify({'error': 'Invalid folder'}), 400
    path = os.path.join(app.config['OUTPUT_FOLDER'], output_dir, 'entry_data.json')
    if not os.path.exists(path):
        return jsonify({'error': 'No entry data saved for this contract'}), 404
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    data['_output_dir'] = output_dir
    return jsonify(data)


if __name__ == '__main__':
    print('Starting Hotel Contract Parser...')
    print('Open: http://localhost:8081')
    app.run(debug=True, host='0.0.0.0', port=8081)
