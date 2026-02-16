# 📩 Order Inbox Extraction Agent  
## OpenAI-only Pipeline (GPT-5.1 + Poppler)

---

## 1) Qëllimi i Projektit

Klienti na ka dhënë akses në **inbox-in e tyre të porosive** ku vijnë rreth **150 porosi në ditë**, nga klientë të ndryshëm dhe në forma të ndryshme.

**Qëllimi:**  
Të ndërtohet një agent që **ekstrakton gjithmonë të njëjtat “Must Fields”**, pavarësisht:
- formatit të porosisë
- strukturës
- burimit (email body, PDF, foto, kombinime)

👉 **E gjithë inteligjenca e ekstraktimit bëhet nga OpenAI – modeli `gpt-5.1-chat-latest`.**

---

## 2) Teknologjitë & Kufizimet (të fiksuara)

### 2.1 Modelet & Engine
- **LLM i vetëm:**  
  `gpt-5.1-chat-latest`
- Nuk përdoren modele të tjera për OCR apo NLP
- OpenAI është **single source of truth** për interpretim dhe ekstraktim

### 2.2 PDF Processing
- PDF-të **nuk lexohen si tekst**
- Për çdo PDF:
  1. Konvertohet në **imazh(e)** duke përdorur **Poppler**
  2. Imazhet dërgohen te OpenAI për vision + extraction

### 2.3 Input Types
- Email body (plain text / HTML)
- PDF attachments → Poppler → image(s)
- Image attachments (jpg, png, webp, scan)
- Kombinime të tyre

---

## 3) Must Fields (obligative)

### 3.1 Kopfdaten (Header Data)
- **Kundennummer** – Customer Number
- **Adressnummer** – Address Number
- **Kom.-Nr.** – Project No.
- **Kom.-Name** – Project Name
- **Liefertermin** – Delivery Date
- **Wunschtermin** – Requested Date  

**Rregull biznesi (i detyrueshëm):**
- Nëse `Wunschtermin` mungon ose është bosh  
  → `Wunschtermin = Liefertermin`

---

### 3.2 Positionsdaten (Item Data)
Për **çdo pozicion / rresht**:
- **Artikelnummer** – Item Number
- **Modellnummer** – Model Number
- **Menge** – Quantity
- **Furncloud-ID** – Furncloud ID

---

## 4) Arkitektura e Përgjithshme (High-Level)

Email Inbox
│
├─ Email Body ───────────────┐
├─ PDF Attachments → Poppler │
│ └─ Images ──────────┼─► OpenAI GPT-5.1
└─ Image Attachments ────────┘
│
Field Extraction
│
Normalization
│
JSON Output


---

## 5) Pipeline i Detajuar

### 5.1 Ingestion
- Lexo:
  - `subject`
  - `sender`
  - `received_at`
  - `email body`
  - `attachments[]`

---

### 5.2 Pre-Processing

#### Email Body
- Nxirret si **raw text**
- HTML → stripped text (pa CSS/JS)
- Dërgohet direkt te OpenAI

#### PDF Attachments
- Çdo PDF:
  - Konvertohet në **imazh për faqe** me Poppler
  - Emërtim p.sh.:  
    `order.pdf_page_1.png`, `order.pdf_page_2.png`
- Imazhet dërgohen te OpenAI (vision input)

#### Image Attachments
- Dërgohen direkt te OpenAI
- Nuk bëhet OCR lokal

---

### 5.3 OpenAI Extraction (core logic)

**Të gjitha inputet (email body + images)** i dërgohen OpenAI me një prompt të strukturuar që kërkon:

- Identifikimin e **Header Data**
- Identifikimin e **Item Data**
- Deduplicim nëse e njëjta vlerë shfaqet disa herë
- Grupim korrekt të item-eve

OpenAI është përgjegjës për:
- OCR (nga imazhet)
- Semantikë (label variacione)
- Strukturim

---

## 6) Rregulla të Ekstraktimit

### 6.1 Gjetja “kudo që janë”
- Një fushë mund të jetë:
  - në email body
  - në PDF image
  - në foto
  - në disa burime njëkohësisht

➡️ Nëse vlera është **e njëjtë** → pranohet pa problem  
➡️ Nëse ka **vlera të ndryshme** → aplikohen rregullat e prioritetit

---

### 6.2 Prioriteti i Burimeve
(Default – konfigurohet)

1. PDF (i konvertuar në image)
2. Email body
3. Image attachments

OpenAI duhet:
- të zgjedhë vlerën finale
- të raportojë konfliktin në metadata

---

### 6.3 Normalizimi
- Datat → `YYYY-MM-DD`
- Quantity:
  - `2`, `2.0`, `2,00` → `2`
- Trim whitespace
- Karaktere speciale të pastruara

---

## 7) Output Standard (JSON)

### 7.1 Struktura e Detyrueshme

```json
{
  "message_id": "string",
  "received_at": "ISO-8601",
  "header": {
    "kundennummer": { "value": "string", "source": "pdf|email|image|derived", "confidence": 0.0 },
    "adressnummer": { "value": "string", "source": "pdf|email|image", "confidence": 0.0 },
    "kom_nr": { "value": "string", "source": "pdf|email|image", "confidence": 0.0 },
    "kom_name": { "value": "string", "source": "pdf|email|image", "confidence": 0.0 },
    "liefertermin": { "value": "YYYY-MM-DD", "source": "pdf|email|image", "confidence": 0.0 },
    "wunschtermin": {
      "value": "YYYY-MM-DD",
      "source": "pdf|email|image|derived",
      "confidence": 1.0,
      "derived_from": "liefertermin"
    }
  },
  "items": [
    {
      "line_no": 1,
      "artikelnummer": { "value": "string", "source": "pdf|email|image", "confidence": 0.0 },
      "modellnummer": { "value": "string", "source": "pdf|email|image", "confidence": 0.0 },
      "menge": { "value": 1, "source": "pdf|email|image", "confidence": 0.0 },
      "furncloud_id": { "value": "string", "source": "pdf|email|image", "confidence": 0.0 }
    }
  ],
  "status": "ok|partial|failed",
  "warnings": [],
  "errors": []
}


8) Statuset

ok
Të gjitha Must Fields (header + items) janë të pranishme

partial
Mungon ≥1 Must Field

failed
Nuk u arrit të nxirret strukturë e përdorshme

9) Acceptance Criteria
Must-Pass

≥95% e porosive:

Header komplet

Items korrekt

100% zbatim i rregullit:

Wunschtermin = Liefertermin kur mungon

JSON valid dhe i qëndrueshëm

Edge Cases

PDF i skanuar

Foto nga mobile

Email body jo-strukturor

Konflikt values (email vs PDF)

10) Deliverables për Developer / Cursor

Service që:

lexon inbox-in

konverton PDF → image me Poppler

dërgon gjithçka te OpenAI GPT-5.1

prodhon JSON sipas këtij spec-i

Prompt template për OpenAI

Config:

source priority

thresholds confidence

Test dataset (email + pdf + image)

11) Parim Kryesor (non-negotiable)

Forma e porosisë nuk ka rëndësi.
OpenAI e lexon, e kupton dhe e strukturon.
Output-i është gjithmonë i njëjtë. 