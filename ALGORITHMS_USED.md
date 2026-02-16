# Algorithms Used in QuickStock Inventory Management System

## Table of Contents
1. [Speech Recognition & NLP Algorithms](#1-speech-recognition--nlp-algorithms)
2. [Text Processing & Normalization](#2-text-processing--normalization)
3. [Pattern Matching & Search Algorithms](#3-pattern-matching--search-algorithms)
4. [Natural Language Understanding (NLU)](#4-natural-language-understanding-nlu)
5. [Data Structures & Storage](#5-data-structures--storage)
6. [Translation & Transliteration](#6-translation--transliteration)
7. [Entity Recognition](#7-entity-recognition)
8. [Summarization](#8-summarization)

---

## 1. Speech Recognition & NLP Algorithms

### 1.1 Vosk Speech-to-Text (Kaldi-based)
**File:** `voice_stream_file.py`  
**Algorithm:** Hidden Markov Models (HMM) + Deep Neural Networks (DNN)

```python
# Dual-language STT using Vosk models
model_hi = Model(hindi_model_path)
model_en = Model(english_model_path)
recognizer_hi = KaldiRecognizer(model_hi, 16000, json.dumps(PRODUCTS))
recognizer_en = KaldiRecognizer(model_en, 16000, json.dumps(PRODUCTS))

def process_pcm_streaming(pcm):
    # Process through Hindi recognizer
    if recognizer_hi.AcceptWaveform(pcm):
        res = json.loads(recognizer_hi.Result())
        final_hi = (res.get("text") or "").strip()
    
    # Process through English recognizer
    if recognizer_en:
        if recognizer_en.AcceptWaveform(pcm):
            res = json.loads(recognizer_en.Result())
            final_en = (res.get("text") or "").strip()
```

**How it works:**
- Uses Kaldi ASR (Automatic Speech Recognition) framework
- HMM for acoustic modeling
- DNN for feature extraction
- Processes 16kHz PCM audio streams
- Supports both partial and final results

---

### 1.2 Language Detection & Merging
**File:** `voice_stream_file.py`  
**Algorithm:** Confidence-based selection using word count heuristic

```python
# If both detected, prefer the longer/more confident one
if final_hi and final_en:
    if len(final_hi.split()) >= len(final_en.split()):
        chosen = final_hi
        chosen_lang = "hi"
    else:
        chosen = final_en
        chosen_lang = "en"

# Build merged Hinglish: Hindi (transliterated) + detected English tokens
merged_hinglish = to_latin(chosen) if chosen_lang == "hi" else chosen
if _english_word_buffer:
    present = set(re.findall(r"[A-Za-z][A-Za-z'\-]*", merged_hinglish))
    new_words = [w for w in _english_word_buffer if w not in present]
    if new_words:
        merged_hinglish = (merged_hinglish + " " + " ".join(new_words)).strip()
```

**How it works:**
- Compares word counts from both recognizers
- Selects language with more words (higher confidence)
- Merges English words from buffer into final result
- Creates Hinglish output combining both languages

---

## 2. Text Processing & Normalization

### 2.1 Indic Text Normalization
**File:** `app.py`  
**Algorithm:** Unicode normalization for Devanagari script

```python
from indicnlp.normalize.indic_normalize import IndicNormalizerFactory

def preprocess_text(text):
    # Normalize Hindi text using Indic NLP normalizer
    if _has_indicnlp_normalizer and re.search(r"[\u0900-\u097F]", text):
        factory = IndicNormalizerFactory()
        normalizer = factory.get_normalizer("hi")
        text = normalizer.normalize(text)
```

**How it works:**
- Normalizes Devanagari Unicode characters
- Handles diacritic variants
- Reduces spelling variations
- Standardizes Hindi text representation

---

### 2.2 Devanagari to ASCII Digit Conversion
**File:** `app.py`  
**Algorithm:** Character mapping using translation table

```python
def preprocess_text(text):
    # Map Devanagari digits to ASCII
    devanagari_digits = str.maketrans('०१२३४५६७८९', '0123456789')
    text = text.translate(devanagari_digits)
```

**How it works:**
- Creates translation table mapping Devanagari digits (०-९) to ASCII (0-9)
- Uses Python's `str.translate()` for O(n) conversion
- Enables consistent number processing

---

### 2.3 Hindi Number Word Parsing
**File:** `app.py`  
**Algorithm:** Recursive descent parser with scale accumulation

```python
def parse_hindi_number_tokens(tok_seq):
    total = 0
    current = 0
    matched_any = False
    
    for tok in tok_seq:
        if tok in digits:
            current += digits[tok]
            matched_any = True
        elif tok in scales:
            if current == 0:
                current = 1
            current *= scales[tok]
            total += current
            current = 0
            matched_any = True
    
    if current > 0:
        total += current
    
    return total if matched_any else None
```

**How it works:**
- Parses Hindi number words (एक, दो, तीन, etc.)
- Handles scales (सौ=100, हज़ार=1000)
- Accumulates values using positional logic
- Example: "दो सौ पचास" → 2×100 + 50 = 250

---

### 2.4 Transliteration (Devanagari ↔ ITRANS)
**File:** `voice_stream_file.py`  
**Algorithm:** Rule-based transliteration using Sanscript

```python
from indic_transliteration.sanscript import transliterate, Devanagari, ITRANS

def to_latin(text):
    if _has_translit and re.search(r"[\u0900-\u097F]", text):
        return transliterate(text, Devanagari, ITRANS)
    return text
```

**How it works:**
- Maps Devanagari characters to Latin script (ITRANS)
- Uses predefined character mapping rules
- Example: "पारले जी" → "paarale jii"

---

## 3. Pattern Matching & Search Algorithms

### 3.1 Regular Expression Pattern Matching
**File:** `app.py`  
**Algorithm:** Regex-based pattern extraction

```python
def parse_quantity_and_unit(text):
    patterns = [
        # "2 kg आटा"
        r'(\d+(?:\.\d+)?)\s*(kg|kilo|kilogram|gram|...|पैकेट|बोतल|पीस)\s+(\w+(?:\s+\w+)*)',
        # "2 आटा" (default unit)
        r'(\d+(?:\.\d+)?)\s+(\w+(?:\s+\w+)*)',
        # "आटा 2 किलो"
        r'(\w+(?:\s+\w+)*)\s+(\d+(?:\.\d+)?)\s*(kg|kilo|...)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            # Extract quantity, unit, product
```

**How it works:**
- Defines multiple regex patterns for different input formats
- Tries patterns sequentially until match found
- Extracts quantity, unit, and product name
- Supports flexible word order

---

### 3.2 Fuzzy String Matching (Difflib)
**File:** `app.py`  
**Algorithm:** Gestalt pattern matching (Ratcliff-Obershelp)

```python
import difflib

def find_product(product_name):
    # Fuzzy fallback for Devanagari names
    if len(product_name) >= 3:
        candidates = list(products.keys())
        matches = difflib.get_close_matches(product_name, candidates, n=1, cutoff=0.75)
        if matches:
            return matches[0]
    return None
```

**How it works:**
- Uses `difflib.get_close_matches()` with 75% similarity threshold
- Compares input against all product names
- Returns best match if similarity ≥ 0.75
- Handles typos and variations

---

### 3.3 Multi-Product Splitting
**File:** `app.py`  
**Algorithm:** Regex-based text segmentation

```python
def parse_multiple_products(text):
    # Split by common separators: 'and', 'aur', 'और', 'तथा', 'व', ',', 'or'
    separators = r'\s*(?:and|aur|और|तथा|व|evam|एवं|or|,)\s*'
    segments = re.split(separators, text, flags=re.IGNORECASE)
    
    results = []
    for segment in segments:
        qty, prod, unit = parse_quantity_and_unit(segment)
        if qty and prod:
            results.append((qty, prod, unit))
    
    return results if results else None
```

**How it works:**
- Splits text on conjunctions (and, और, aur, etc.)
- Processes each segment independently
- Returns list of (quantity, product, unit) tuples
- Example: "2 lays और 3 parle g" → [(2, 'लेज़', 'पैकेट'), (3, 'पारले जी', 'पैकेट')]

---

### 3.4 Keyword Detection
**File:** `app.py`  
**Algorithm:** Substring search with keyword lists

```python
def process_text_command(text, apply=True):
    # Check for RESTOCK keywords
    restock_keywords = ['आ गया', 'आ गए', 'आया', 'जोड़', 'डाल', 'मिला']
    restock_found = any(keyword in text for keyword in restock_keywords)
    
    # Check for SALE keywords
    sale_keywords = ['बेचा', 'बेचे', 'बिक', 'दिया', 'ग्राहक']
    sale_found = any(keyword in text for keyword in sale_keywords)
```

**How it works:**
- Maintains predefined keyword lists for actions
- Uses `any()` with substring search
- Determines transaction type (sale vs restock)
- O(n×m) where n=keywords, m=text length

---

## 4. Natural Language Understanding (NLU)

### 4.1 Intent Classification
**File:** `app.py`  
**Algorithm:** Rule-based classification with keyword matching

```python
def process_text_command(text, apply=True):
    # Parse quantity, product, and unit
    quantity, product_key, unit = parse_quantity_and_unit(text)
    
    # Determine action based on keywords
    if restock_found and not sale_found:
        action = 'restock'
    else:
        action = 'sale'  # Default
```

**How it works:**
- Extracts entities (quantity, product, unit)
- Classifies intent using keyword presence
- Priority: explicit restock > default sale
- Returns structured action object

---

### 4.2 Entity Extraction
**File:** `app.py`  
**Algorithm:** Hybrid approach (spaCy NER + Regex)

```python
def extract_entities(text):
    entities = []
    nlp = get_spacy_nlp()
    
    if nlp:
        # Use spaCy NER
        doc = nlp(text)
        for ent in doc.ents:
            entities.append({'text': ent.text, 'label': ent.label_})
    else:
        # Fallback: regex-based extraction
        nums = re.findall(r'\b\d+(?:\.\d+)?\b', text)
        for n in nums:
            entities.append({'text': n, 'label': 'NUMBER'})
        
        dates = re.findall(r'\b(?:today|tomorrow|yesterday|\d{1,2}/\d{1,2}/\d{2,4})\b', text)
        for d in dates:
            entities.append({'text': d, 'label': 'DATE'})
    
    return entities
```

**How it works:**
- Primary: Uses spaCy's pre-trained NER model
- Fallback: Regex patterns for numbers and dates
- Returns list of (entity_text, entity_label) pairs

---

## 5. Data Structures & Storage

### 5.1 In-Memory Dictionary (Hash Table)
**File:** `app.py`  
**Algorithm:** Python dict (hash table implementation)

```python
products = {
    "पारले जी": {"current_stock": 100, "threshold": 20, "unit": "पैकेट", "base_unit": "पैकेट"},
    "लेज़": {"current_stock": 50, "threshold": 15, "unit": "पैकेट", "base_unit": "पैकेट"},
    # ...
}

# O(1) lookup, insert, update
products[product_key]["current_stock"] += quantity
```

**How it works:**
- Hash table for O(1) average-case operations
- Nested dictionaries for product attributes
- Direct key-based access for inventory updates

---

### 5.2 Transaction Log (List/Array)
**File:** `app.py`  
**Algorithm:** Append-only list with LIFO retrieval

```python
transaction_log = []

# Append transaction (O(1))
transaction_log.append({
    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'action': 'sale',
    'product': product_key,
    'quantity': quantity,
    'unit': display_unit,
    'old_stock': old_stock,
    'new_stock': new_stock
})

# Get recent transactions (O(1) slicing)
recent = transaction_log[-50:][::-1]  # Last 50, reversed
```

**How it works:**
- Dynamic array (Python list)
- Append-only for chronological order
- Negative indexing for recent items
- Reversal for newest-first display

---

### 5.3 CSV File Storage
**File:** `app.py`  
**Algorithm:** Sequential file I/O with CSV format

```python
def save_transaction_to_csv(transaction):
    file_exists = os.path.exists(TRANSACTIONS_CSV)
    
    with open(TRANSACTIONS_CSV, 'a', newline='', encoding='utf-8') as f:
        fieldnames = ['timestamp', 'action', 'product', 'quantity', 'unit', 'old_stock', 'new_stock']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        
        if not file_exists:
            writer.writeheader()
        
        writer.writerow(transaction)

def load_transactions_from_csv():
    transactions = []
    with open(TRANSACTIONS_CSV, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            transactions.append(row)
    return transactions
```

**How it works:**
- Append mode for new transactions (O(1))
- Sequential read for loading (O(n))
- CSV format for portability
- UTF-8 encoding for Hindi text support

---

### 5.4 Pending Confirmations Queue
**File:** `app.py`  
**Algorithm:** List-based queue with ID-based lookup

```python
pending_confirmations = []

# Add to queue (O(1))
pending_confirmations.append({
    'id': len(pending_confirmations),
    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'original_text': text,
    'preprocessed_text': processed_text,
    'nlu_result': nlu_result
})

# Remove by ID (O(n) linear search)
for i, p in enumerate(pending_confirmations):
    if p['id'] == action_id:
        pending = pending_confirmations.pop(i)
        break
```

**How it works:**
- List-based FIFO queue
- Auto-incrementing IDs
- Linear search for removal (acceptable for small queues)
- Supports edit-before-confirm workflow

---

## 6. Translation & Transliteration

### 6.1 Machine Translation (Google Translator API)
**File:** `voice_stream_file.py`  
**Algorithm:** Neural Machine Translation (NMT)

```python
from deep_translator import GoogleTranslator, MyMemoryTranslator

def to_english(text):
    if _has_translator:
        # Primary: Google Translate
        translated = GoogleTranslator(source='hi', target='en').translate(text)
        if translated and translated.strip() and translated.strip() != text.strip():
            return translated
        
        # Fallback: MyMemory
        fallback = MyMemoryTranslator(source='hi', target='en').translate(text)
        if fallback and fallback.strip():
            return fallback
    return text
```

**How it works:**
- Uses Google's NMT model (Transformer-based)
- Fallback to MyMemory for reliability
- Handles Hindi → English translation
- Caches results to avoid redundant API calls

---

## 7. Entity Recognition

### 7.1 spaCy Named Entity Recognition
**File:** `app.py`  
**Algorithm:** BiLSTM-CRF (Bidirectional LSTM with Conditional Random Fields)

```python
def extract_entities(text):
    nlp = get_spacy_nlp()
    if nlp:
        doc = nlp(text)
        for ent in doc.ents:
            entities.append({'text': ent.text, 'label': ent.label_})
```

**How it works:**
- Pre-trained spaCy model (en_core_web_sm)
- BiLSTM for sequence encoding
- CRF layer for entity boundary detection
- Recognizes: PERSON, ORG, DATE, MONEY, etc.

---

## 8. Summarization

### 8.1 Extractive Summarization (LexRank)
**File:** `app.py`  
**Algorithm:** Graph-based ranking (LexRank)

```python
from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.lex_rank import LexRankSummarizer

def summarize_text(text, sentences_count=3):
    parser = PlaintextParser.from_string(text, Tokenizer("english"))
    summarizer = LexRankSummarizer()
    summary = summarizer(parser.document, sentences_count)
    return " ".join([str(sentence) for sentence in summary])
```

**How it works:**
- Creates sentence similarity graph
- Uses PageRank-like algorithm (LexRank)
- Ranks sentences by centrality
- Extracts top N sentences
- Similar to Google's PageRank but for sentences

---

## 9. ASR Error Correction

### 9.1 N-gram Fuzzy Matching
**File:** `app.py`  
**Algorithm:** Character n-gram similarity with fuzzy matching

```python
def auto_correct_asr(text, product_names=None, fuzzy_cutoff=0.78, top_n_grams=3):
    cache = load_asr_cache()
    words = text.split()
    corrected_words = []
    
    for word in words:
        # Check cache first
        if word in cache:
            corrected_words.append(cache[word])
            continue
        
        # Try fuzzy matching against product names
        if product_names:
            matches = difflib.get_close_matches(word, product_names, n=1, cutoff=fuzzy_cutoff)
            if matches:
                chosen = matches[0]
                cache[word] = chosen
                corrected_words.append(chosen)
                continue
        
        corrected_words.append(word)
    
    save_asr_cache(cache)
    return " ".join(corrected_words)
```

**How it works:**
- Splits text into words
- Checks persistent cache for known corrections
- Uses fuzzy matching (difflib) against product names
- Threshold: 78% similarity
- Caches corrections for future use
- Reduces API calls and improves speed

---

## 10. Unit Conversion

### 10.1 Measurement Unit Normalization
**File:** `app.py`  
**Algorithm:** Lookup table with multiplicative conversion

```python
unit_conversions = {
    'kg': 1, 'kilo': 1, 'kilogram': 1,
    'grams': 0.001, 'gram': 0.001, 'g': 0.001,
    'liters': 1, 'liter': 1, 'l': 1,
    'ml': 0.001, 'milliliter': 0.001,
    'किलो': 1, 'ग्राम': 0.001, 'लीटर': 1,
    # ...
}

def parse_quantity_and_unit(text):
    if unit and unit in unit_conversions:
        base_quantity = quantity * unit_conversions[unit]
        actual_quantity = base_quantity / unit_conversions[products[product_key]['base_unit']]
```

**How it works:**
- Hash table for O(1) unit lookup
- Converts to base unit (kg, liter, packet)
- Normalizes across different unit representations
- Example: 500g → 0.5kg, 1000ml → 1L

---

## Summary Table

| Algorithm | Type | Complexity | Use Case |
|-----------|------|------------|----------|
| Vosk STT | Deep Learning (HMM+DNN) | O(n) | Speech recognition |
| Fuzzy Matching | String similarity | O(n×m) | Product name matching |
| Regex Parsing | Pattern matching | O(n) | Quantity/unit extraction |
| Hash Table | Data structure | O(1) avg | Inventory storage |
| LexRank | Graph-based | O(n²) | Text summarization |
| spaCy NER | BiLSTM-CRF | O(n) | Entity extraction |
| NMT | Transformer | O(n²) | Translation |
| N-gram Matching | String similarity | O(n×m) | ASR correction |
| Keyword Search | String matching | O(n×m) | Intent classification |
| CSV I/O | Sequential file | O(n) | Transaction persistence |

---

## Technology Stack

**Core Libraries:**
- **Vosk**: Offline speech recognition (Kaldi-based)
- **spaCy**: NLP and NER
- **Sumy**: Text summarization
- **difflib**: Fuzzy string matching
- **deep_translator**: Machine translation
- **indic-nlp**: Hindi text normalization
- **Flask**: Web framework
- **CSV**: Data persistence

**Algorithms Summary:**
- 10+ distinct algorithms
- Mix of rule-based and ML-based approaches
- Optimized for Hindi/Hinglish processing
- Real-time performance for voice input
