# XXLUTZ Order Extraction Agent

An automated order extraction system specifically designed for **XXLUTZ/MÖMAX** furniture orders. This service reads orders from an email inbox, processes email content and PDF attachments using OpenAI GPT, and produces structured JSON and XML output.

## Supported Order Formats

### Format 1: Standard XXLUTZ Orders (Email + PDF)
- Email body with structured order data
- Optional furnplan PDF/TIF attachment with detailed article specifications
- Common fields: KDNR, ILN codes, Komm (commission), Liefertermin (KW format)
- Article codes like `CQ9606XA-60951` split into modellnummer + artikelnummer

### Format 2: MÖMAX Branch Orders (Email only)
- Email body with "Lagerbestellung" format
- No PDF attachment required
- TYP-based article codes
- Common for stock orders from MÖMAX branches

## Quick Start

1. **Install Python 3.10+**

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment** - Create a `.env` file:
   ```env
   # OpenAI Configuration
   OPENAI_API_KEY=your_api_key_here
   OPENAI_MODEL=gpt-5.1-chat-latest
   
   # Poppler Path (for PDF conversion)
   POPPLER_PATH=C:/path/to/poppler/bin
   
   # Email Configuration
   EMAIL_PROTOCOL=imap
   EMAIL_HOST=your.mail.server.com
   EMAIL_PORT=993
   EMAIL_USER=your_email@example.com
   EMAIL_PASSWORD=your_password
   EMAIL_SSL=true
   EMAIL_FOLDER=INBOX
   EMAIL_SEARCH=UNSEEN
   EMAIL_MARK_SEEN=true
   
   # SMTP (auto-send reply-needed emails)
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=your_email@example.com
   SMTP_PASSWORD=your_password
   SMTP_SSL=true
   
   # Reply-needed email settings
   REPLY_EMAIL_TO=00primex.eu@gmail.com
   REPLY_EMAIL_BODY=Please send the order with furnplan or make the order with 2 positions.
   
   # Processing Options
   OUTPUT_DIR=output
   SOURCE_PRIORITY=pdf,email,image
   EMAIL_POLL_SECONDS=30
   EMAIL_ONLY_AFTER_START=true
   ```

4. **Run the extraction service:**
   ```bash
   python main.py
   ```

## Output

The system generates two types of output for each processed order:

### JSON Output
Complete extracted data including all fields, confidence scores, and source information.

### XML Output (Two files per order)
- `OrderInfo_[name].xml` - Order header information (customer, delivery, store details)
- `OrderArticleInfo_[name].xml` - Detailed article specifications with dimensions and configurations

## Web Dashboard

Review and manage extracted orders through the Flask web interface:

```bash
python app.py
```

Open: `http://127.0.0.1:5000`

## React Dashboard + API

The project now includes a separate React dashboard (`front-end/my-react-app`) that consumes authenticated backend APIs under `/api/*`.

### Backend environment variables (dashboard/API)

Add these to `.env` for API access from the React app:

```env
DASHBOARD_TOKEN=your_secure_token_here
DASHBOARD_ALLOWED_ORIGINS=https://dashboard.example.com,http://localhost:5173
```

- `DASHBOARD_TOKEN` is required for all `/api/*` and `/api/files/*` endpoints.
- `DASHBOARD_ALLOWED_ORIGINS` must list allowed frontend origins for CORS.

### Frontend environment variables

Create `front-end/my-react-app/.env` from `.env.example`:

```env
VITE_API_BASE_URL=http://127.0.0.1:5000
```

Use an absolute backend URL when frontend and backend are separately deployed.

### Local development (backend + frontend)

1. Start backend:
   ```bash
   python app.py
   ```
2. Start frontend:
   ```bash
   cd front-end/my-react-app
   npm install
   npm run dev
   ```

### Deployment notes

- Keep backend and frontend deploys separate if needed.
- Set `DASHBOARD_ALLOWED_ORIGINS` to deployed frontend URL(s).
- Keep `DASHBOARD_TOKEN` secret and pass it only via frontend login/token entry.

## Key Configuration Options

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_MODEL` | `gpt-5.1-chat-latest` | OpenAI model for extraction |
| `POPPLER_PATH` | - | Path to Poppler binaries (pdftoppm) |
| `SOURCE_PRIORITY` | `pdf,email,image` | Trust priority when data conflicts |
| `PDF_DPI` | `300` | Resolution for PDF to image conversion |
| `MAX_PDF_PAGES` | `10` | Maximum PDF pages to process |
| `EMAIL_POLL_SECONDS` | `30` | Polling interval (0 for single run) |
| `EMAIL_ONLY_AFTER_START` | `true` | Only process new emails |
| `EMAIL_MARK_SEEN` | `false` | Mark processed emails as read/deleted (prevents re-processing) |
| `SMTP_HOST` | - | SMTP host for sending reply-needed emails |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | - | SMTP username (also used as From) |
| `SMTP_PASSWORD` | - | SMTP password/app password |
| `SMTP_SSL` | `true` | Use TLS (STARTTLS on 587; SSL on 465) |
| `REPLY_EMAIL_TO` | `00primex.eu@gmail.com` | Recipient for reply-needed notifications |
| `REPLY_EMAIL_BODY` | - | First line of the reply-needed email body |
| `DASHBOARD_TOKEN` | - | Required Bearer token for `/api/*` and protected file downloads |
| `DASHBOARD_ALLOWED_ORIGINS` | - | Comma-separated CORS allowlist for dashboard frontend origins |

## Data Files

The system uses Excel files for customer/ILN lookup:
- `Primex_Kunden.xlsb` - Customer database with address matching
- `ALL ILN LISTE_*.xlsx` - ILN number lookup
- `Lieferlogik.xlsx` - Delivery week calculation rules

## Project Structure

```
├── main.py              # Entry point - email polling and processing
├── pipeline.py          # Main processing pipeline
├── openai_extract.py    # OpenAI API integration
├── prompts.py           # XXLUTZ extraction prompts
├── prompts_detail.py    # Furnplan detail extraction prompts
├── normalize.py         # Data normalization and field mapping
├── lookup.py            # Excel customer/ILN lookup
├── delivery_logic.py    # Delivery week calculation
├── xml_exporter.py      # XML output generation
├── email_ingest.py      # Email reading (IMAP/POP3)
├── app.py               # Flask web dashboard
├── config.py            # Configuration management
└── XXLUTZ CASES/        # Sample test cases
```

## Test Cases

The `XXLUTZ CASES/` folder contains sample orders for testing:
- **ORDER 1-4**: Standard format with email + PDF attachment
- **ORDER 5-6**: MÖMAX branch format (email only)
