from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, flash
import os
import sys
from werkzeug.utils import secure_filename
import tempfile
from datetime import datetime
import json

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from main import parse_pdf

app = Flask(__name__)
app.secret_key = 'hotel-contract-parser-secret-key'

# Configure upload folder
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'outputs'
ALLOWED_EXTENSIONS = {'pdf'}

# Create directories if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file selected'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'Only PDF files are allowed'}), 400
    
    try:
        # Save uploaded file
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Get form options
        output_dir = os.path.join(app.config['OUTPUT_FOLDER'], f"output_{timestamp}")
        semi_auto = request.form.get('semi_auto') == 'on'
        year_override = request.form.get('year', '').strip() or None
        
        # Process the PDF
        result = parse_pdf(
            pdf_path=filepath,
            output_dir=output_dir,
            semi_auto=semi_auto,
            year_override=year_override
        )
        
        return jsonify({
            'success': True,
            'message': 'PDF processed successfully!',
            'csv_file': os.path.basename(result),
            'output_dir': f"output_{timestamp}"
        })
        
    except Exception as e:
        return jsonify({'error': f'Error processing PDF: {str(e)}'}), 500

@app.route('/download/<output_dir>/<filename>')
def download_file(output_dir, filename):
    try:
        file_path = os.path.join(app.config['OUTPUT_FOLDER'], output_dir, filename)
        return send_file(file_path, as_attachment=True)
    except Exception as e:
        return jsonify({'error': f'Error downloading file: {str(e)}'}), 500

@app.route('/logs/<output_dir>')
def view_logs(output_dir):
    try:
        log_dir = os.path.join(app.config['OUTPUT_FOLDER'], output_dir, 'logs')
        logs = {}
        
        # Try to read JSON log
        json_log_path = os.path.join(log_dir, 'audit_log.json')
        if os.path.exists(json_log_path):
            with open(json_log_path, 'r', encoding='utf-8') as f:
                logs['json'] = json.load(f)
        
        # Try to read text log
        txt_log_path = os.path.join(log_dir, 'audit_log.txt')
        if os.path.exists(txt_log_path):
            with open(txt_log_path, 'r', encoding='utf-8') as f:
                logs['text'] = f.read()
        
        return jsonify(logs)
    except Exception as e:
        return jsonify({'error': f'Error reading logs: {str(e)}'}), 500

if __name__ == '__main__':
    print("Starting Hotel Contract Parser Web Interface...")
    print("Open your browser and go to: http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)
