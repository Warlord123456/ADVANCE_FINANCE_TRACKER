import os
import re
import io
import sys
import tempfile
import logging
import shutil
import platform
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Tuple, Dict, Any, List, Optional

from PIL import Image, ImageOps
import pytesseract
from flask import (
    Flask, render_template, request, redirect, url_for,
    jsonify, send_file, flash
)
from werkzeug.utils import secure_filename
from concurrent.futures import ThreadPoolExecutor, as_completed
import pdf2image

# Configure Tesseract executable path based on the operating system.
if platform.system() == "Windows":
    tesseract_executable = os.path.join(os.getcwd(), "tesseract", "tesseract.exe")
    if os.path.exists(tesseract_executable):
        pytesseract.pytesseract.tesseract_cmd = tesseract_executable
        print(f"Using Tesseract from: {tesseract_executable}")
    else:
        print("Tesseract executable not found in the local 'tesseract' folder.")
else:
    tesseract_path = shutil.which("tesseract")
    if tesseract_path:
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
        print(f"Tesseract found at: {tesseract_path}")
    else:
        print("Tesseract not found. Make sure it is installed.")

# Import the database and models.
from extensions import db
from models import Receipt, ReceiptItem

#########################################
#        Helper Conversion Functions    #
#########################################
def parse_date(date_str: Optional[str]) -> datetime:
    """
    Parse a date string using multiple formats. If no valid date is found,
    returns the current UTC time.
    """
    if not date_str:
        return datetime.utcnow()
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%m-%d-%Y'):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return datetime.utcnow()


def parse_decimal(value: Optional[str]) -> Decimal:
    """
    Clean a string and convert it to a Decimal. If conversion fails, returns 0.00.
    """
    if not value:
        return Decimal('0.00')
    cleaned = re.sub(r'[^\d.,-]', '', value)
    if ',' in cleaned and '.' in cleaned:
        cleaned = cleaned.replace(',', '')
    elif ',' in cleaned and '.' not in cleaned:
        cleaned = cleaned.replace(',', '.')
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return Decimal('0.00')


#########################################
#            Application Setup          #
#########################################
def create_app() -> Flask:
    """
    Create and configure the Flask application.
    """
    app = Flask(__name__)

    class Config:
        SECRET_KEY = os.getenv('SECRET_KEY', 'your-secret-key')
        SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URI', 'sqlite:///receipts.db')
        UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
        MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB
        ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}
        POPPLER_PATH = os.getenv('POPPLER_PATH') or os.path.abspath(
            os.path.join(os.getcwd(), "poppler-24.08.0", "Library", "bin")
        )

    app.config.from_object(Config)
    db.init_app(app)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    app.logger.setLevel(logging.DEBUG)

    def allowed_file(filename: str) -> bool:
        """
        Check if the file has one of the allowed extensions.
        """
        return (
            '.' in filename and
            filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']
        )

    def preprocess_image(file_path: str) -> str:
        """
        Preprocess the image by converting it to grayscale and applying a threshold.
        Returns the path to the preprocessed image.
        """
        try:
            with Image.open(file_path) as img:
                gray_img = ImageOps.grayscale(img)
                # Apply a simple binary threshold
                threshold_img = gray_img.point(lambda x: 0 if x < 128 else 255, mode='1')
                preprocessed_path = f"{os.path.splitext(file_path)[0]}_preprocessed.jpg"
                threshold_img.save(preprocessed_path)
                app.logger.debug(f"Preprocessed image saved at {preprocessed_path}")
                return preprocessed_path
        except Exception as e:
            app.logger.exception(f"Error preprocessing image {file_path}: {e}")
            raise

    def ocr_receipt(file_path: str) -> Tuple[str, str]:
        """
        Perform OCR on an image file after preprocessing. Save the OCR output
        to a text file and return both the OCR text and the text file path.
        """
        try:
            preprocessed_path = preprocess_image(file_path)
            with Image.open(preprocessed_path) as processed_img:
                ocr_text = pytesseract.image_to_string(processed_img)
            text_file_path = f"{os.path.splitext(file_path)[0]}.txt"
            with open(text_file_path, 'w', encoding='utf-8') as f:
                f.write(ocr_text)
            app.logger.debug(f"OCR text saved at {text_file_path}")
            return ocr_text, text_file_path
        except Exception as e:
            app.logger.exception(f"OCR error processing {file_path}: {e}")
            return "", ""

    # Alias for clarity
    perform_ocr = ocr_receipt

    def extract_receipt_details(ocr_text: str) -> Dict[str, Any]:
        """
        Extract receipt details such as merchant name, bill number, date, items,
        total amount, tax, discount, and location from the OCR text.
        """
        details: Dict[str, Any] = {
            'bill_no': None,
            'merchant': None,
            'date_time': None,
            'items': [],
            'total_amount': None,
            'tax': None,
            'discount': None,
            'location': None
        }

        lines = [line.strip() for line in ocr_text.splitlines() if line.strip()]

        # Attempt to detect merchant name (preferring lines with alphabetic characters)
        for line in lines:
            if re.match(r'^[A-Za-z\s&\-.]+$', line):
                details['merchant'] = line
                break
        if details['merchant'] is None and lines:
            details['merchant'] = lines[0]

        # Extract bill/invoice number using common patterns.
        bill_no_patterns = [
            r'\b(?:Bill|Invoice)\s*(?:No\.?|#)[:\s]*([\w-]+)',
            r'\b(?:BILL|INVOICE)\s*(?:NO\.?|#)[:\s]*([\w-]+)'
        ]
        for line in lines:
            for pattern in bill_no_patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    details['bill_no'] = match.group(1)
                    break
            if details['bill_no']:
                break

        # Extract date/time from the receipt.
        date_patterns = [
            r'\b(?P<day>\d{1,2})[/-](?P<month>\d{1,2})[/-](?P<year>\d{2,4})\b',
            r'\b(?P<year>\d{4})[/-](?P<month>\d{1,2})[/-](?P<day>\d{1,2})\b'
        ]
        for line in lines:
            for pattern in date_patterns:
                match = re.search(pattern, line)
                if match:
                    details['date_time'] = match.group(0)
                    break
            if details['date_time']:
                break

        # Extract total amount.
        total_patterns = [
            r'\b(?:TOTAL|Grand Total|AMOUNT|Amount)\b[^\d\$€£]*([\$€£]?\s*\d{1,3}(?:[,\s]\d{3})*(?:\.\d{2})?)',
            r'([\$€£]\s*\d{1,3}(?:[,\s]\d{3})*(?:\.\d{2}))\s*(?:TOTAL|Grand Total)?'
        ]
        for line in lines:
            for pattern in total_patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    details['total_amount'] = match.group(1).strip()
                    break
            if details['total_amount']:
                break

        # Extract individual items and their prices.
        item_pattern = r'^(?P<item>.+?)\s+(?P<price>[\$€£]?\s*\d+(?:[,\s]\d+)*(?:\.\d{1,2})?)\s*$'
        for line in lines:
            if re.search(r'\b(total|amount|tax|discount|invoice|bill)\b', line, re.IGNORECASE):
                continue
            match = re.match(item_pattern, line)
            if match:
                item_name = match.group('item').strip(' -')
                price = match.group('price').strip()
                details['items'].append({'name': item_name, 'amount': price})
                app.logger.debug(f"Extracted item: '{item_name}' with price: '{price}'")
            else:
                app.logger.debug(f"Item extraction: No match for line: '{line}'")

        # Extract tax amount.
        tax_pattern = r'\b(?:Tax|VAT)\b[^\d\$€£]*([\$€£]?\s*\d{1,3}(?:[,\s]\d{3})*(?:\.\d{2})?)'
        for line in lines:
            match = re.search(tax_pattern, line, re.IGNORECASE)
            if match:
                details['tax'] = match.group(1).strip()
                break

        # Extract discount amount.
        discount_pattern = r'\b(?:Discount|Disc\.?)\b[^\d\$€£]*([\$€£]?\s*\d{1,3}(?:[,\s]\d{3})*(?:\.\d{2})?)'
        for line in lines:
            match = re.search(discount_pattern, line, re.IGNORECASE)
            if match:
                details['discount'] = match.group(1).strip()
                break

        return details

    def categorize_expense(merchant: Optional[str], items: List[Dict[str, str]]) -> str:
        """
        Categorize the expense based on the merchant name and item keywords.
        """
        categories = {
            'grocery': ['grocery', 'supermarket', 'market'],
            'dining': ['restaurant', 'cafe', 'diner'],
            'travel': ['uber', 'lyft', 'taxi', 'flight'],
            'entertainment': ['movie', 'cinema', 'theater'],
            'shopping': ['store', 'mall', 'shopping']
        }
        if merchant:
            merchant_lower = merchant.lower()
            for category, keywords in categories.items():
                if any(keyword in merchant_lower for keyword in keywords):
                    return category
        return 'others'

    def process_pdf(file_path: str) -> str:
        """
        Convert a PDF file to images using Poppler, perform OCR on each page,
        and aggregate the OCR text.
        """
        full_ocr_text = ""
        try:
            poppler_path = app.config['POPPLER_PATH']
            app.logger.debug(f"Using Poppler path: {poppler_path}")
            images = pdf2image.convert_from_path(file_path, poppler_path=poppler_path)
            app.logger.debug(f"Converted PDF to {len(images)} image(s).")
            for idx, image in enumerate(images):
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
                    temp_image_path = temp_file.name
                try:
                    image.save(temp_image_path, format='PNG')
                    app.logger.debug(f"Saved temporary image for PDF page {idx + 1}: {temp_image_path}")
                    page_text, _ = perform_ocr(temp_image_path)
                    full_ocr_text += page_text + "\n"
                except Exception as e:
                    app.logger.exception(f"Error processing PDF page {idx + 1}: {e}")
                finally:
                    try:
                        os.remove(temp_image_path)
                        app.logger.debug(f"Removed temporary file: {temp_image_path}")
                    except OSError as e:
                        app.logger.error(f"Error removing temporary file {temp_image_path}: {e}")
        except Exception as e:
            app.logger.exception(f"Error converting PDF {file_path}: {e}")
        return full_ocr_text

    def process_receipt_file(file_path: str) -> Optional[Receipt]:
        """
        Process an uploaded receipt file (PDF or image), perform OCR, extract details,
        and save the receipt and its items to the database.
        """
        with app.app_context():
            try:
                if file_path.lower().endswith('.pdf'):
                    ocr_text = process_pdf(file_path)
                else:
                    ocr_text, _ = perform_ocr(file_path)
            except Exception as e:
                app.logger.exception(f"Error processing file {file_path}: {e}")
                return None

            if not ocr_text.strip():
                app.logger.warning(f"No OCR text extracted from {file_path}")
                return None

            details = extract_receipt_details(ocr_text)
            if not details.get('merchant'):
                details['merchant'] = "Unknown Merchant"
            category = categorize_expense(details.get('merchant'), details.get('items'))

            receipt_date = parse_date(details.get('date_time'))
            total_amt = parse_decimal(details.get('total_amount'))
            tax_amt = parse_decimal(details.get('tax'))
            discount_amt = parse_decimal(details.get('discount'))

            try:
                receipt = Receipt(
                    bill_no=details.get('bill_no'),
                    merchant=details.get('merchant'),
                    date_time=receipt_date,
                    total_amount=total_amt,
                    tax=tax_amt,
                    discount=discount_amt,
                    ocr_text=ocr_text,
                    category=category,
                    location=details.get('location')
                )
                db.session.add(receipt)
                db.session.commit()

                # Process individual receipt items.
                for item in details.get('items', []):
                    if item.get('name') and item.get('amount'):
                        receipt_item = ReceiptItem(
                            receipt_id=receipt.id,
                            name=item.get('name'),
                            amount=parse_decimal(item.get('amount'))
                        )
                        db.session.add(receipt_item)
                db.session.commit()
                app.logger.info(f"Successfully processed receipt with ID: {receipt.id}")
                return receipt
            except Exception as e:
                app.logger.exception(f"Database error processing {file_path}: {e}")
                db.session.rollback()
                return None

    #########################################
    #             Application Routes        #
    #########################################
    @app.route('/')
    def index():
        """Dashboard view: lists receipts and shows aggregated statistics."""
        receipts = Receipt.query.order_by(Receipt.id.desc()).all()
        total_amount = sum(float(r.total_amount) for r in receipts if r.total_amount)
        average_amount = total_amount / len(receipts) if receipts else 0.0
        return render_template('dashboard.html',
                               receipts=receipts,
                               total_amount=total_amount,
                               average_amount=average_amount)

    @app.route('/upload', methods=['GET', 'POST'])
    def upload():
        """
        Handle file uploads. Uses a ThreadPoolExecutor to process multiple
        receipt files concurrently.
        """
        if request.method == 'POST':
            files = request.files.getlist('receipt_files')
            if not files:
                flash('No files selected.', 'warning')
                return redirect(request.url)
            processed_files: List[str] = []
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = []
                for file in files:
                    if file and allowed_file(file.filename):
                        filename = secure_filename(file.filename)
                        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                        file.save(file_path)
                        processed_files.append(filename)
                        futures.append(executor.submit(process_receipt_file, file_path))
                    else:
                        app.logger.warning(f"File {file.filename} is not allowed.")
                for future in as_completed(futures):
                    try:
                        _ = future.result()
                    except Exception as e:
                        app.logger.exception(f"Error processing a receipt: {e}")
            flash(f'Uploaded {len(processed_files)} receipt(s). They are processing in the background.', 'success')
            return redirect(url_for('index'))
        return render_template('upload.html')

    @app.route('/reports')
    def reports():
        """
        Generate reports summarizing expenses by category and month.
        """
        receipts = Receipt.query.order_by(Receipt.id.desc()).all()
        category_data: Dict[str, float] = {}
        monthly_data: Dict[str, float] = {}
        for receipt in receipts:
            cat = receipt.category or 'others'
            amt = float(receipt.total_amount) if receipt.total_amount else 0.0
            category_data[cat] = category_data.get(cat, 0.0) + amt
            try:
                month_key = receipt.date_time.strftime('%Y-%m')
            except Exception:
                month_key = 'unknown'
            monthly_data[month_key] = monthly_data.get(month_key, 0.0) + amt
        monthly_data = dict(sorted(monthly_data.items()))
        return render_template('reports.html',
                               category_data=category_data,
                               monthly_data=monthly_data,
                               receipts=receipts)

    @app.route('/receipt/<int:receipt_id>/edit', methods=['GET', 'POST'])
    def edit_receipt(receipt_id: int):
        """
        Edit a specific receipt. On POST, update the receipt details in the database.
        """
        receipt = Receipt.query.get_or_404(receipt_id)
        if request.method == 'POST':
            receipt.merchant = request.form.get('merchant')
            receipt.date_time = parse_date(request.form.get('date_time'))
            receipt.total_amount = parse_decimal(request.form.get('total_amount'))
            receipt.tax = parse_decimal(request.form.get('tax'))
            receipt.discount = parse_decimal(request.form.get('discount'))
            receipt.category = request.form.get('category')
            receipt.ocr_text = request.form.get('ocr_text')
            receipt.location = request.form.get('location')
            try:
                db.session.commit()
                flash('Receipt updated successfully.', 'success')
            except Exception as e:
                app.logger.exception(f"Error updating receipt {receipt_id}: {e}")
                db.session.rollback()
                flash('Error updating receipt.', 'danger')
            return redirect(url_for('index'))
        return render_template('edit_receipt.html', receipt=receipt)

    @app.route('/export/<string:export_format>')
    def export_data(export_format: str):
        """
        Export receipt data in CSV format. Currently, only CSV export is supported.
        """
        if export_format.lower() != 'csv':
            flash("Only CSV export is supported.", "warning")
            return redirect(url_for('index'))
        import csv
        receipts = Receipt.query.all()
        output_stream = io.StringIO()
        writer = csv.writer(output_stream)
        writer.writerow(['ID', 'Merchant', 'Date', 'Total Amount', 'Tax', 'Discount', 'Category'])
        for r in receipts:
            writer.writerow([
                r.id,
                r.merchant,
                r.date_time.isoformat() if r.date_time else '',
                float(r.total_amount) if r.total_amount else '',
                float(r.tax) if r.tax else '',
                float(r.discount) if r.discount else '',
                r.category
            ])
        output_data = output_stream.getvalue()
        return send_file(
            io.BytesIO(output_data.encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name='receipts.csv'
        )

    @app.route('/ocr_preview', methods=['POST'])
    def ocr_preview():
        """
        Provide a preview of the OCR output for an uploaded file.
        """
        file = request.files.get('file')
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            ocr_text, ocr_text_file = perform_ocr(file_path)
            return jsonify({'ocr_text': ocr_text, 'text_file': ocr_text_file})
        return jsonify({'error': 'No file uploaded or file type not allowed.'}), 400

    @app.route('/voice_search', methods=['POST'])
    def voice_search():
        """
        Search receipts based on a voice-to-text query.
        """
        query = request.form.get('query')
        if not query:
            return jsonify({'error': 'No query provided.'}), 400
        receipts = Receipt.query.filter(Receipt.ocr_text.contains(query)).all()
        result = [
            {'id': r.id, 'merchant': r.merchant, 'total': float(r.total_amount) if r.total_amount else 0.0}
            for r in receipts
        ]
        return jsonify(result)

    @app.route('/notifications')
    def notifications():
        """Return notifications (currently an empty list)."""
        return jsonify({'notifications': []})

    @app.route('/service-worker.js')
    def service_worker():
        """Serve the service worker script for PWA support."""
        return app.send_static_file('js/service-worker.js')

    return app

# Create a module-level app variable for WSGI servers.
app = create_app()

# When running locally, initialize the database and run the server.
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
