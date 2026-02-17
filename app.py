import requests
from flask import Flask, request, jsonify, send_file
import os
import re
import json
import csv
import speech_recognition as sr
import difflib
from difflib import SequenceMatcher
import urllib.parse
from datetime import datetime, date
try:
    from indicnlp.normalize.indic_normalize import IndicNormalizerFactory
    _has_indicnlp_normalizer = True
except Exception:
    _has_indicnlp_normalizer = False
try:
    from indic_transliteration.sanscript import transliterate, Devanagari, ITRANS
    _has_indic = True
except Exception:
    _has_indic = False
# Sumy imports are made lazy inside summarize_text to avoid optional deps at startup

# Optional: spaCy for basic NER (install model with `python -m spacy download en_core_web_sm`)
try:
    import spacy
    _spacy_available = True
except Exception:
    spacy = None
    _spacy_available = False

# Lazy-loaded spaCy model cache
_spacy_nlp = None

def get_spacy_nlp():
    """Return a loaded spaCy nlp object for 'en_core_web_sm'.
    If model not found, attempt to download it. If download or load fails, return None."""
    global _spacy_nlp
    if not _spacy_available:
        return None

    if _spacy_nlp is not None:
        return _spacy_nlp

    try:
        # First try to load
        _spacy_nlp = spacy.load('en_core_web_sm')
        return _spacy_nlp
    except Exception as e:
        print(f"WARNING: spaCy model load failed: {e}")
        # Attempt to download the model if possible
        try:
            from spacy.cli import download as spacy_download
            print("INFO: Attempting to download 'en_core_web_sm' model...")
            spacy_download('en_core_web_sm')
            _spacy_nlp = spacy.load('en_core_web_sm')
            return _spacy_nlp
        except Exception as e2:
            print(f"WARNING: Could not download/load spaCy model: {e2}")
            _spacy_nlp = None
            return None

app = Flask(__name__)

# Create uploads directory if it doesn't exist
os.makedirs('./test_audio_files', exist_ok=True)

# CSV file path for storing completed transactions
TRANSACTIONS_CSV = os.path.join(os.path.dirname(__file__), 'transactions_history.csv')

# Transaction log to track all inventory changes
transaction_log = []

# Pending confirmations from voice input
pending_confirmations = []

# Global status of Android Client
android_client_connected = False

# Hindi to English product name mapping
product_name_english = {
    "पारले जी": "Parle-G",
    "लेस": "Lays",
    "डाबर हनी": "Dabur Honey",
    "टाटा नमक": "Tata Salt",
    "कोक": "Coke",
    "साबुन": "Soap",
    "आटा": "Wheat Flour",
    "चावल": "Rice",
    "दाल": "Lentils",
    "चीनी": "Sugar",
    "तेल": "Oil",
    "दूध": "Milk",
    "चाय": "Tea"
}

# Hindi to English unit name mapping
unit_name_english = {
    "पैकेट": "Packet",
    "बोतल": "Bottle",
    "पीस": "Piece",
    "किलो": "Kg",
    "ग्राम": "Gram",
    "लीटर": "Liter",
    "मिलीलीटर": "ml"
}

# Enhanced database with measurement units and base units
# Enhanced database with measurement units and base units
products = {
    "पारले जी": {"current_stock": 100, "threshold": 20, "unit": "पैकेट", "base_unit": "पैकेट", "price": 10},
    "लेस": {"current_stock": 50, "threshold": 15, "unit": "पैकेट", "base_unit": "पैकेट", "price": 20},
    "डाबर हनी": {"current_stock": 30, "threshold": 10, "unit": "बोतल", "base_unit": "बोतल", "price": 150},
    "टाटा नमक": {"current_stock": 80, "threshold": 25, "unit": "पैकेट", "base_unit": "पैकेट", "price": 25},
    "कोक": {"current_stock": 40, "threshold": 12, "unit": "बोतल", "base_unit": "बोतल", "price": 40},
    "साबुन": {"current_stock": 25, "threshold": 8, "unit": "पीस", "base_unit": "पीस", "price": 35},

    "आटा": {"current_stock": 100, "threshold": 25, "unit": "किलो", "base_unit": "किलो", "price": 45},
    "चावल": {"current_stock": 150, "threshold": 30, "unit": "किलो", "base_unit": "किलो", "price": 60},
    "दाल": {"current_stock": 80, "threshold": 20, "unit": "किलो", "base_unit": "किलो", "price": 120},
    "चीनी": {"current_stock": 60, "threshold": 15, "unit": "किलो", "base_unit": "किलो", "price": 42},

    "तेल": {"current_stock": 50, "threshold": 12, "unit": "लीटर", "base_unit": "लीटर", "price": 180},
    "दूध": {"current_stock": 40, "threshold": 10, "unit": "लीटर", "base_unit": "लीटर", "price": 66},
    "चाय": {"current_stock": 5, "threshold": 2, "unit": "किलो", "base_unit": "किलो", "price": 450},
}

# Measurement unit conversions (to base units)
unit_conversions = {
    # English
    'kg': 1, 'kilo': 1, 'kilogram': 1,
    'grams': 0.001, 'gram': 0.001, 'g': 0.001, 'gm': 0.001,
    'liters': 1, 'liter': 1, 'l': 1,
    'ml': 0.001, 'milliliter': 0.001,
    'packets': 1, 'packet': 1, 'pkt': 1,
    'bottles': 1, 'bottle': 1,
    'pieces': 1, 'piece': 1, 'pcs': 1,
    # Devanagari
    'किलो': 1,
    'ग्राम': 0.001,
    'ग्रा': 0.001,
    'लीटर': 1,
    'मिलीलीटर': 0.001,
    'पैकेट': 1,
    'बोतल': 1,
    'पीस': 1,
}

# Text preprocessing functions
def preprocess_text(text):
    """Preprocess the input text for better NLU understanding."""
    if not text:
        return ""
    
    print(f"Original text: '{text}'")

    # Normalize Hindi text using Indic NLP normalizer (reduces spelling/diacritic variants)
    try:
        if _has_indicnlp_normalizer and re.search(r"[\u0900-\u097F]", text):
            _normalizer = getattr(preprocess_text, "_indic_normalizer", None)
            if _normalizer is None:
                factory = IndicNormalizerFactory()
                preprocess_text._indic_normalizer = factory.get_normalizer("hi")
                _normalizer = preprocess_text._indic_normalizer
            text = _normalizer.normalize(text)
            print(f"[DEBUG] After IndicNLP normalize: '{text}'")
    except Exception as _e:
        print(f"[DEBUG] IndicNLP normalize skipped: {_e}")

    # --- Normalize Hindi numerals and number words to ASCII digits ---
    try:
        # Map Devanagari digits to ASCII
        devanagari_digits = str.maketrans('०१२३४५६७८९', '0123456789')
        text = text.translate(devanagari_digits)

        # Base Hindi number words to digits
        hindi_number_words = {
            'शून्य': '0', 'एक': '1', 'दो': '2', 'तीन': '3', 'चार': '4',
            'पाँच': '5', 'पांच': '5', 'छह': '6', 'सात': '7', 'आठ': '8', 'नौ': '9',
            'दस': '10', 'ग्यारह': '11', 'बारह': '12', 'तेरह': '13', 'चौदह': '14',
            'पंद्रह': '15', 'पन्द्रह': '15', 'सोलह': '16', 'सत्रह': '17', 'अठारह': '18', 'उन्नीस': '19',
            'बीस': '20', 'इक्कीस': '21', 'बाइस': '22', 'तेईस': '23', 'चौबीस': '24', 'पच्चीस': '25',
            'छब्बीस': '26', 'सत्ताईस': '27', 'अट्ठाईस': '28', 'उनतीस': '29', 'उन्तीस': '29',
            'तीस': '30', 'इकतीस': '31', 'इकत्तीस': '31', 'बत्तीς': '32', 'तैंतीस': '33', 'चौंतीस': '34', 'पैंतीस': '35',
            'छत्तीस': '36', 'सैंतीस': '37', 'अड़तीस': '38', 'अडतीस': '38', 'उनतालीस': '39',
            'चालीस': '40', 'इकतालीस': '41', 'बयालीस': '42', 'तैंतालीस': '43', 'चवालीस': '44', 'पैंतालीस': '45',
            'छयालिस': '46', 'सैंतालीस': '47', 'अड़तालीस': '48', 'अड़तालीस': '48', 'उनचास': '49',
            'पचास': '50', 'इक्याबन': '51', 'बावन': '52', 'त्रिपन': '53', 'चौवन': '54', 'पचपन': '55',
            'छप्पन': '56', 'सत्तावन': '57', 'अठावन': '58', 'उनसठ': '59',
            'साठ': '60', 'इकसठ': '61', 'बासठ': '62', 'तिरसठ': '63', 'चौंसठ': '64', 'पैंसठ': '65',
            'छियासठ': '66', 'सड़सठ': '67', 'सड़सठ': '67', 'अड़सठ': '68', 'अड़सठ': '68', 'उनहत्तर': '69',
            'सत्तर': '70', 'इकहत्तर': '71', 'बहत्तर': '72', 'तिहत्तर': '73', 'चौहत्तर': '74', 'पचहत्तर': '75',
            'छिहत्तर': '76', 'सतहत्तर': '77', 'अठहत्तर': '78', 'उन्नासी': '79',
            'अस्सी': '80', 'इक्यासी': '81', 'बयासी': '82', 'तिरासी': '83', 'चौरासी': '84', 'पचासी': '85',
            'छियासी': '86', 'सत्तासी': '87', 'अठासी': '88', 'नवासी': '89',
            'नब्बे': '90', 'इक्यानवे': '91', 'बयानवे': '92', 'तिरानवे': '93', 'चौरानवे': '94', 'पचानवे': '95',
            'छियानवे': '96', 'सत्तानवे': '97', 'अट्ठानवे': '98', 'निन्यानवे': '99',
            'सौ': '100'
        }

        # Compositional Hindi number parser for short phrases (e.g., "दो सौ बीस")
        units = {
            'शून्य':0,'एक':1,'दो':2,'तीन':3,'चार':4,'पांच':5,'पाँच':5,'छह':6,'सात':7,'आठ':8,'नौ':9,
            'दस':10,'ग्यारह':11,'बारह':12,'तेरह':13,'चौदह':14,'पंद्रह':15,'पन्द्रह':15,'सोलह':16,'सत्रह':17,'अठारह':18,'उन्नीस':19
        }
        tens = {
            'बीस':20,'तीस':30,'चालीस':40,'पचास':50,'साठ':60,'सत्तर':70,'अस्सी':80,'नब्बे':90
        }
        scales = {'सौ':100,'हज़ार':1000,'हजार':1000}

        def parse_hindi_number_tokens(tok_seq):
            total = 0
            current = 0
            matched_any = False
            for tok in tok_seq:
                if tok in hindi_number_words:
                    # Direct mapped composite word
                    current += int(hindi_number_words[tok])
                    matched_any = True
                elif tok in units:
                    current += units[tok]
                    matched_any = True
                elif tok in tens:
                    current += tens[tok]
                    matched_any = True
                elif tok in scales:
                    if current == 0:
                        current = 1
                    current *= scales[tok]
                    total += current
                    current = 0
                    matched_any = True
                else:
                    return None
            return total + current if matched_any else None

        # Token scan: replace sequences of number words with digits
        tokens = text.split()
        i = 0
        out_tokens = []
        while i < len(tokens):
            parsed = None
            parsed_len = 0
            # try up to 4-word spans
            for span in (4,3,2,1):
                if i+span <= len(tokens):
                    val = parse_hindi_number_tokens(tokens[i:i+span])
                    if val is not None:
                        parsed = str(val)
                        parsed_len = span
                        break
            if parsed is not None:
                out_tokens.append(parsed)
                i += parsed_len
            else:
                # single-word direct mapping fallback
                w = tokens[i]
                out_tokens.append(hindi_number_words.get(w, w))
                i += 1
        text = ' '.join(out_tokens)
        print(f"[DEBUG] After Hindi number normalization: '{text}'")
    except Exception as _e:
        print(f"[DEBUG] Number normalization skipped: {_e}")

    # Convert to lowercase
    text = text.lower().strip()
    
    # Remove extra whitespace
    text = ' '.join(text.split())
    print(f"[DEBUG] After trim/lower: '{text}'")
    
    # Common Hinglish corrections and normalization
    corrections = {
        'beech': 'beche', 'bich': 'beche', 'bikgayi': 'bik gayi', 'bikgaya': 'bik gaya',
        'aagaya': 'aa gaya', 'aagaye': 'aa gaye', 'aaya': 'aa gaya', 'aaye': 'aa gaye',
        'daldo': 'daal do', 'addkardo': 'add kar do', 'stockcheck': 'stock check',
        'kitnabacha': 'kitna bacha', 'kitnebacha': 'kitna bacha',
        'bechi': 'beche', 'bechai': 'beche', 'bech': 'beche',
        'kilo': 'kg', 'kilogram': 'kg', 'grams': 'g', 'gram': 'g',
        'liters': 'l', 'liter': 'l', 'milliliter': 'ml',
    }
    
    # Apply corrections
    words = text.split()
    corrected_words = []
    
    for word in words:
        if word in corrections:
            corrected_words.append(corrections[word])
        else:
            corrected_words.append(word)
    
    text = ' '.join(corrected_words)
    print(f"[DEBUG] After Hinglish corrections: '{text}'")

    # Automatic ASR correction (fuzzy + cache + optional LLM)
    try:
        # lazy import local helper (defined below)
        text = auto_correct_asr(text, product_names=list(products.keys()))
        print(f"[DEBUG] After ASR auto-correct: '{text}'")
    except Exception as e:
        print(f"ASR auto-correct failed: {e}")
    
    # Remove common filler words
    filler_words = ['please', 'ji', 'hey', 'hello', 'okay', 'ok', 'toh', 'to', 'the', 'a', 'of']
    words = text.split()
    words = [word for word in words if word not in filler_words]
    text = ' '.join(words)
    
    print(f"Preprocessed text: '{text}'")
    return text

# Enhanced helper function for product name matching (no fuzzy)
def find_product(product_name):
    """Finds a product by fuzzy name matching."""
    product_name = product_name.strip()
    print(f"[DEBUG] find_product input: '{product_name}'")
    
    # Exact match
    if product_name in products:
        print(f"[DEBUG] find_product exact match: '{product_name}'")
        return product_name
    
    # Partial match (only for sufficiently long tokens)
    if len(product_name) >= 3:
        for known_product in products.keys():
            if product_name in known_product or known_product in product_name:
                print(f"[DEBUG] find_product partial matched '{product_name}' -> '{known_product}'")
                return known_product
    
    # Common Hindi product name mappings
    hindi_to_english = {
    'आटा': 'आटा',
    'मैदा': 'आटा',

    'चावल': 'चावल',
    'राइस': 'चावल',

    'दाल': 'दाल',

    'नमक': 'टाटा नमक',
    'टाटा नमक': 'टाटा नमक',

    'शहद': 'डाबर हनी',
    'हनी': 'डाबर हनी',

    'चीनी': 'चीनी',
    'शक्कर': 'चीनी',

    'तेल': 'तेल',
    'ऑयल': 'तेल',

    'दूध': 'दूध',
    'मिल्क': 'दूध',

    'चाय': 'चाय',
    'टी': 'चाय',

    'पारले जी': 'पारले जी',
    'लेज़': 'लेज़',
    'कोक': 'कोक',
    'साबुन': 'साबुन',
}

    
    if product_name in hindi_to_english:
        print(f"[DEBUG] find_product mapped '{product_name}' -> '{hindi_to_english[product_name]}'")
        return hindi_to_english[product_name]

    # Fuzzy fallback (difflib) for Devanagari names
    if len(product_name) >= 3:
        candidates = list(products.keys())
        matches = difflib.get_close_matches(product_name, candidates, n=1, cutoff=0.75)
        if matches:
            print(f"[DEBUG] find_product fuzzy matched '{product_name}' -> '{matches[0]}'")
            return matches[0]

    return None

def parse_multiple_products_by_numbers(text):
    """Parse multiple products using number positions as delimiters.
    Examples: '2 lays 3 parle g' or 'lays 2 parle g 3'
    Returns list of (quantity, product_key, unit) tuples."""
    print(f"[DEBUG] parse_multiple_products_by_numbers input: '{text}'")
    
    # Find all numbers (digits) and their positions in the text
    number_pattern = r'\d+(?:\.\d+)?'
    numbers = []
    for match in re.finditer(number_pattern, text):
        numbers.append({
            'value': float(match.group()),
            'start': match.start(),
            'end': match.end(),
            'text': match.group()
        })
    
    # Also check for Hindi number words that might not have been converted
    hindi_numbers = {
        'एक': 1, 'दो': 2, 'तीन': 3, 'चार': 4, 'पाँच': 5, 'पांच': 5,
        'छह': 6, 'सात': 7, 'आठ': 8, 'नौ': 9, 'दस': 10
    }
    tokens_temp = text.split()
    for idx, token in enumerate(tokens_temp):
        if token in hindi_numbers:
            # Calculate approximate position
            pos = sum(len(t) + 1 for t in tokens_temp[:idx])
            numbers.append({
                'value': float(hindi_numbers[token]),
                'start': pos,
                'end': pos + len(token),
                'text': token
            })
            print(f"[DEBUG] Found Hindi number word '{token}' = {hindi_numbers[token]}")
    
    # Sort by position
    numbers.sort(key=lambda x: x['start'])
    
    print(f"[DEBUG] Found {len(numbers)} numbers: {[n['text'] for n in numbers]}")
    print(f"[DEBUG] Full text being parsed: '{text}'")
    tokens = text.split()
    print(f"[DEBUG] Tokens: {tokens}")
    
    if len(numbers) < 2:
        # Less than 2 numbers, not a multi-product command
        print(f"[DEBUG] ⚠️ Only {len(numbers)} number(s) found, not multi-product - will try conjunction-based")
        return None
    
    results = []
    tokens = text.split()
    used_products = set()  # Track which products have been used to avoid duplicates
    used_token_indices = set()  # Track which token positions have been used
    
    # Track occurrence count for each unique number text
    occurrence_tracker = {}
    
    # Strategy: Each number represents a quantity for a product
    # Look for product names near each number
    for i, num_info in enumerate(numbers):
        quantity = num_info['value']
        
        # Extract text around this number
        # Get tokens before and after the number
        num_token_idx = None
        num_text = num_info['text']
        
        # Track which occurrence of this specific number text we're looking for
        if num_text not in occurrence_tracker:
            occurrence_tracker[num_text] = 0
        occurrence_tracker[num_text] += 1
        target_occurrence = occurrence_tracker[num_text]
        
        # Find the target_occurrence-th occurrence of this number (could be digit or Hindi word)
        current_occurrence = 0
        for idx, token in enumerate(tokens):
            if idx in used_token_indices:
                continue  # Skip already used positions
            
            if num_text in token or token == num_text:
                current_occurrence += 1
                if current_occurrence == target_occurrence:
                    num_token_idx = idx
                    used_token_indices.add(idx)
                    print(f"[DEBUG] Found number '{num_text}' (occurrence {target_occurrence}) at token index {idx}")
                    break
        
        if num_token_idx is None:
            print(f"[DEBUG] Could not find token index for number '{num_text}' (occurrence {target_occurrence})")
            continue
        
        # Look for product name after the number (most common: "2 lays")
        product_text = None
        unit = None
        
        # Define keywords to skip
        keywords = ['बेचा', 'बेचे', 'बिक', 'दिया', 'आ', 'गया', 'गए', 'आया', 'जोड़', 'डाल', 'मिला', 'और', 'and', 'aur']
        
        # Check tokens after the number
        for offset in range(1, min(5, len(tokens) - num_token_idx)):
            candidate = tokens[num_token_idx + offset]
            
            # Check if it's a unit
            if candidate.lower() in unit_conversions:
                unit = candidate.lower()
                print(f"[DEBUG] Found unit '{unit}' after number at offset {offset}")
                # Product might be after the unit: "2 kg aata"
                if num_token_idx + offset + 1 < len(tokens):
                    next_token = tokens[num_token_idx + offset + 1]
                    # Check if next token is not a number
                    if not re.match(r'^\d+(?:\.\d+)?$', next_token):
                        product_text = next_token
                        print(f"[DEBUG] Found product '{product_text}' after unit")
                        # Check for multi-word product names (but stop at next number)
                        if num_token_idx + offset + 2 < len(tokens):
                            next_next = tokens[num_token_idx + offset + 2]
                            if not re.match(r'^\d+(?:\.\d+)?$', next_next) and next_next.lower() not in keywords:
                                product_text += " " + next_next
                                print(f"[DEBUG] Extended product name to '{product_text}'")
                        break
                continue
            
            # Check if it's a number (next product's quantity)
            if re.match(r'^\d+(?:\.\d+)?$', candidate):
                break
            
            # Check if it's a keyword (skip)
            if candidate.lower() in keywords:
                continue
            
            # This is likely the product name
            product_text = candidate
            # Check for multi-word product names
            if num_token_idx + offset + 1 < len(tokens):
                next_token = tokens[num_token_idx + offset + 1]
                # If next token is not a number and not a keyword, it's part of product name
                if not re.match(r'^\d+(?:\.\d+)?$', next_token) and next_token.lower() not in keywords:
                    product_text += " " + next_token
            break
        
        # If no product found after number, check before (less common: "lays 2")
        if not product_text and num_token_idx > 0:
            for offset in range(1, min(3, num_token_idx + 1)):
                candidate = tokens[num_token_idx - offset]
                
                # Check if it's a unit
                if candidate.lower() in unit_conversions:
                    unit = candidate.lower()
                    continue
                
                # Check if it's a number
                if re.match(r'^\d+(?:\.\d+)?$', candidate):
                    break
                
                # Check if it's a keyword (keywords already defined above)
                if candidate.lower() in keywords:
                    continue
                
                product_text = candidate
                # Check for multi-word product names before
                if num_token_idx - offset - 1 >= 0:
                    prev_token = tokens[num_token_idx - offset - 1]
                    if not re.match(r'^\d+(?:\.\d+)?$', prev_token) and prev_token.lower() not in keywords:
                        product_text = prev_token + " " + product_text
                break
        
        if product_text:
            product_key = find_product(product_text)
            if product_key:
                # Check if this product has already been used
                if product_key in used_products:
                    print(f"[DEBUG] Product '{product_key}' already used, skipping duplicate")
                    continue
                
                # Use detected unit or product's default unit
                if not unit:
                    unit = products[product_key]['unit']
                
                results.append((quantity, product_key, unit))
                used_products.add(product_key)
                print(f"[DEBUG] Extracted: qty={quantity}, product={product_key}, unit={unit}")
            else:
                print(f"[DEBUG] Product '{product_text}' not found in inventory")
    
    return results if len(results) >= 2 else None

def parse_multiple_products_by_conjunctions(text):
    """Parse multiple products by splitting on conjunctions (FALLBACK METHOD).
    Examples: '2 lays और 3 parle g'
    Returns list of (quantity, product_key, unit) tuples."""
    print(f"[DEBUG] parse_multiple_products_by_conjunctions input: '{text}'")
    
    # Split by common separators: 'and', 'aur', 'और', 'तथा', 'व', ',', 'or', 'evam'
    # Pattern allows optional spaces around separators
    separators = r'\s*(?:and|aur|और|तथा|व|evam|एवं|or|,)\s*'
    segments = re.split(separators, text, flags=re.IGNORECASE)
    
    print(f"[DEBUG] Split into segments: {segments}")
    
    results = []
    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        
        qty, prod, unit = parse_quantity_and_unit(segment)
        if qty and prod:
            results.append((qty, prod, unit))
            print(f"[DEBUG] Parsed segment '{segment}' -> qty={qty}, product={prod}, unit={unit}")
    
    return results if results else None

def parse_multiple_products(text):
    """Parse multiple products from text using multiple strategies.
    Primary: Number-based detection ('2 lays 3 parle g')
    Fallback: Conjunction-based splitting ('2 lays और 3 parle g')
    Returns list of (quantity, product_key, unit) tuples."""
    
    print(f"[DEBUG] ========== MULTI-PRODUCT PARSING ==========")
    print(f"[DEBUG] Input text: '{text}'")
    
    # Strategy 1: Number-based detection (PRIMARY)
    print(f"[DEBUG] Trying Strategy 1: Number-based detection...")
    results = parse_multiple_products_by_numbers(text)
    if results and len(results) >= 2:
        print(f"[DEBUG] ✅ Number-based parsing succeeded with {len(results)} products")
        print(f"[DEBUG] Results: {results}")
        return results
    else:
        print(f"[DEBUG] ❌ Number-based parsing returned: {results}")
    
    # Strategy 2: Conjunction-based splitting (FALLBACK)
    print(f"[DEBUG] Trying Strategy 2: Conjunction-based splitting...")
    results = parse_multiple_products_by_conjunctions(text)
    if results and len(results) >= 2:
        print(f"[DEBUG] ✅ Conjunction-based parsing succeeded with {len(results)} products")
        print(f"[DEBUG] Results: {results}")
        return results
    else:
        print(f"[DEBUG] ❌ Conjunction-based parsing returned: {results}")
    
    print(f"[DEBUG] ❌ Both multi-product parsing strategies failed")
    print(f"[DEBUG] ==========================================")
    return None

def parse_quantity_and_unit(text):
    """Parse quantity and unit from text, converting to base units."""
    print(f"[DEBUG] parse_quantity_and_unit input: '{text}'")
    # First, handle 'quantity + unit' only (no product specified)
    unit_pattern = r'^(\d+(?:\.\d+)?)\s*(kg|kilo|kilogram|gram|g|gm|liters?|liter|l|ml|milliliter|packets?|packet|pkt|bottles?|bottle|pieces?|piece|pcs|किलो|ग्राम|ग्रा|लीटर|मिलीलीटर|पैकेट|बोतल|पीस)\s*$'
    m_unit_only = re.search(unit_pattern, text)
    if m_unit_only:
        try:
            qty = float(m_unit_only.group(1))
            unit = m_unit_only.group(2).lower()
            print(f"[DEBUG] Detected quantity+unit only: qty={qty}, unit='{unit}', no product")
            return qty, None, unit
        except Exception as _e:
            print(f"[DEBUG] Unit-only parse failed: {_e}")

    # Check if text contains conjunctions - if so, it might be a multi-product command
    # that failed to parse, so return None to avoid incorrect parsing
    conjunctions = ['और', 'aur', 'and', 'तथा', 'व', 'evam', 'एवं', 'or', ',']
    if any(conj in text.lower() for conj in conjunctions):
        print(f"[DEBUG] Text contains conjunctions, might be multi-product. Skipping single-product parse.")
        # Still try to parse, but be more careful
    
    # Patterns for different quantity formats
    patterns = [
        r'(\d+(?:\.\d+)?)\s*(kg|kilo|kilogram|gram|g|gm|liters?|liter|l|ml|milliliter|packets?|packet|pkt|bottles?|bottle|pieces?|piece|pcs|किलो|ग्राम|ग्रा|लीटर|मिलीलीटर|पैकेट|बोतल|पीस)\s+(\w+(?:\s+\w+)*)',  # "2 kg आटा"
        r'(\d+(?:\.\d+)?)\s+(\w+(?:\s+\w+)*)',  # "2 आटा" (default unit)
        r'(\w+(?:\s+\w+)*)\s+(\d+(?:\.\d+)?)\s*(kg|kilo|kilogram|gram|g|gm|liters?|liter|l|ml|milliliter|packets?|packet|pkt|bottles?|bottle|pieces?|piece|pcs|किलो|ग्राम|ग्रा|लीटर|मिलीलीटर|पैकेट|बोतल|पीस)',  # "आटा 2 किलो"
    ]
    
    for pattern in patterns:
        print(f"[DEBUG] Trying pattern: {pattern}")
        match = re.search(pattern, text)
        if match:
            print(f"[DEBUG] Regex matched groups: {match.groups()}")
            if len(match.groups()) == 3:
                # Validate that group(1) is actually a number
                try:
                    quantity = float(match.group(1))
                except ValueError:
                    # Group 1 is not a number, skip this pattern
                    print(f"[DEBUG] Group 1 '{match.group(1)}' is not a number, trying next pattern")
                    continue
                unit = match.group(2).lower()
                product_text = match.group(3)
            else:
                # Validate that group(1) is actually a number
                try:
                    quantity = float(match.group(1))
                except ValueError:
                    # Group 1 is not a number, skip this pattern
                    print(f"[DEBUG] Group 1 '{match.group(1)}' is not a number, trying next pattern")
                    continue
                product_text = match.group(2)
                unit = None  # Will use product's default unit
                # If the second group is actually a unit, treat as unit-only input
                if product_text in unit_conversions:
                    print(f"[DEBUG] Second group is a unit ('{product_text}'); no product provided")
                    return quantity, None, product_text
            
            product_key = find_product(product_text)
            
            if product_key:
                # If unit is specified, convert to product's base unit
                if unit and unit in unit_conversions:
                    base_quantity = quantity * unit_conversions[unit]
                    actual_quantity = base_quantity / unit_conversions[products[product_key]['base_unit']]
                    print(f"[DEBUG] Parsed quantity={quantity}, unit='{unit}', product='{product_key}', actual_quantity={actual_quantity}")
                    return actual_quantity, product_key, unit
                else:
                    # Use product's default unit
                    print(f"[DEBUG] Parsed quantity={quantity}, default unit for product='{product_key}'")
                    return quantity, product_key, products[product_key]['unit']
    
    # Fallback: simple number and product detection
    words = text.split()
    print(f"[DEBUG] Fallback parsing tokens: {words}")
    quantity = None
    product_key = None
    unit = None
    
    for i, word in enumerate(words):
        # Check if word is a number
        if word.replace('.', '').isdigit():
            quantity = float(word)
            # Look for product in surrounding words
            for j in range(max(0, i-2), min(len(words), i+3)):
                potential_product = find_product(words[j])
                if potential_product:
                    product_key = potential_product
                    unit = products[product_key]['unit']
                    break
            break
    
    return quantity, product_key, unit

def transcribe_audio_sr(filepath):
    """Transcribe audio using SpeechRecognition."""
    recognizer = sr.Recognizer()
    try:
        with sr.AudioFile(filepath) as source:
            print("Listening to audio...")
            audio = recognizer.record(source)
        text = recognizer.recognize_google(audio, language="en-IN")
        return text
    except sr.UnknownValueError:
        print("Could not understand audio")
        return ""


# --- ASR auto-correction helpers ---
_ASR_CACHE_PATH = os.path.join(os.path.dirname(__file__), "asr_corrections_cache.json")
_ASR_LOG_PATH = os.path.join(os.path.dirname(__file__), "asr_corrections_log.jsonl")
_ASR_REVIEW_PATH = os.path.join(os.path.dirname(__file__), "asr_corrections_review.json")

def load_asr_cache():
    if os.path.exists(_ASR_CACHE_PATH):
        try:
            with open(_ASR_CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_asr_cache(cache):
    try:
        with open(_ASR_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def append_asr_log(fragment, chosen, source="auto", confidence=1.0):
    rec = {
        "fragment": fragment,
        "chosen": chosen,
        "source": source,
        "confidence": float(confidence),
        "timestamp": datetime.utcnow().isoformat()
    }
    try:
        with open(_ASR_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass

def auto_correct_asr(text, product_names=None, openai_api_key=None, llm_timeout_seconds=8,
                     fuzzy_cutoff=0.78, top_n_grams=3):
    """Auto-correct likely ASR mishearings against product_names.
    Uses a small persistent cache to remember mappings. Optional LLM path omitted by default.
    """
    if product_names is None:
        product_names = []

    cache = load_asr_cache()

    words = text.split()
    corrected_words = []
    i = 0
    N = len(words)

    while i < N:
        matched = False
        for n in range(min(top_n_grams, N - i), 0, -1):
            fragment = " ".join(words[i:i+n]).lower()
            # cached?
            if fragment in cache:
                corrected = cache[fragment]
                corrected_words.extend(corrected.split())
                i += n
                matched = True
                break

            # Fuzzy match against product names (difflib)
            close = difflib.get_close_matches(fragment, product_names, n=1, cutoff=fuzzy_cutoff)
            if close:
                candidate = close[0]
                cache[fragment] = candidate
                # compute rough confidence by sequence matcher
                conf = SequenceMatcher(None, fragment, candidate).ratio()
                append_asr_log(fragment, candidate, source="auto", confidence=conf)
                corrected_words.extend(candidate.split())
                i += n
                matched = True
                break

            # Secondary best-score scan
            best = None
            best_score = 0.0
            for p in product_names:
                score = SequenceMatcher(None, fragment, p).ratio()
                if score > best_score:
                    best_score = score
                    best = p
            if best and best_score >= fuzzy_cutoff:
                cache[fragment] = best
                append_asr_log(fragment, best, source="auto", confidence=best_score)
                corrected_words.extend(best.split())
                i += n
                matched = True
                break

        if not matched:
            token = words[i].lower()
            # optional LLM path — omitted by default for privacy/cost
            if openai_api_key and token.isalpha():
                try:
                    import openai
                    openai.api_key = openai_api_key
                    prompt = (
                        "You are a helper that maps noisy ASR tokens to product names.\n"
                        f"Product list: {', '.join(product_names)}\n\n"
                        f"ASR token: '{token}'\n"
                        "If token is a mishearing of a product name, return the exact product name; otherwise return NOCHANGE."
                    )
                    resp = openai.ChatCompletion.create(
                        model="gpt-3.5-turbo",
                        messages=[{"role":"user","content":prompt}],
                        max_tokens=32,
                        temperature=0.0,
                        timeout=llm_timeout_seconds,
                    )
                    llm_choice = resp["choices"][0]["message"]["content"].strip()
                    if llm_choice and llm_choice != "NOCHANGE":
                        cache[token] = llm_choice
                        append_asr_log(token, llm_choice, source="llm", confidence=1.0)
                        corrected_words.extend(llm_choice.split())
                        i += 1
                        continue
                except Exception:
                    pass

            corrected_words.append(words[i])
            i += 1

    save_asr_cache(cache)
    return " ".join(corrected_words)


def summarize_text(text, sentences_count=3):
    """Simple extractive summarization using Sumy (LexRank)."""
    if not text or len(text.split()) < 30:
        return text  # short text, no need to summarize

    try:
        # Lazy import to avoid pulling NLTK/regex at startup
        from sumy.parsers.plaintext import PlaintextParser
        from sumy.nlp.tokenizers import Tokenizer
        from sumy.summarizers.lex_rank import LexRankSummarizer
        parser = PlaintextParser.from_string(text, Tokenizer("english"))
        summarizer = LexRankSummarizer()
        summary_sentences = summarizer(parser.document, sentences_count)
        summary = ' '.join(str(s) for s in summary_sentences)
        return summary
    except Exception as e:
        print(f"Summarization failed: {e}")
        return text


def extract_entities(text):
    """Extract simple named entities using spaCy if available; returns list of (text, label).
    Falls back to simple regex-based extraction for numbers/dates if spaCy not installed."""
    entities = []
    if not text:
        return entities

    if _spacy_available:
        try:
            nlp = get_spacy_nlp()
            if nlp:
                doc = nlp(text)
                for ent in doc.ents:
                    entities.append({'text': ent.text, 'label': ent.label_})
                return entities
        except Exception as e:
            print(f"spaCy NER failed: {e}")

    # Fallback simple extraction: numbers, percentages, dates (very basic)
    nums = re.findall(r'\b\d+(?:\.\d+)?\b', text)
    for n in nums:
        entities.append({'text': n, 'label': 'NUMBER'})

    # Very naive date/time capture
    dates = re.findall(r'\b(?:today|tomorrow|yesterday|\d{1,2}/\d{1,2}/\d{2,4})\b', text, flags=re.I)
    for d in dates:
        entities.append({'text': d, 'label': 'DATE'})

    return entities

def process_multiple_products_command(original_text, products_list, apply=True):
    """Process multiple products in a single command.
    products_list: list of (quantity, product_key, unit) tuples"""
    
    # Determine action type from keywords
    restock_keywords = ['आ गया', 'आ गए', 'आया', 'जोड़', 'डाल', 'मिला']
    sale_keywords = ['बेचा', 'बेचे', 'बिक', 'दिया', 'ग्राहक']
    
    restock_found = any(keyword in original_text for keyword in restock_keywords)
    sale_found = any(keyword in original_text for keyword in sale_keywords)
    
    # Determine action
    if restock_found and not sale_found:
        action_type = 'restock'
    else:
        action_type = 'sale'
    
    print(f"[DEBUG] Multiple products detected: {len(products_list)} items, action: {action_type}")
    
    results = []
    errors = []
    
    for quantity, product_key, unit in products_list:
        display_unit = unit if unit else products[product_key]['unit']
        
        if action_type == 'restock':
            new_stock = products[product_key]["current_stock"] + quantity
            if apply:
                old_stock = products[product_key]["current_stock"]
                products[product_key]["current_stock"] = new_stock
                trans = {
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'action': 'restock',
                    'product': product_key,
                    'quantity': quantity,
                    'unit': display_unit,
                    'old_stock': old_stock,
                    'new_stock': new_stock
                }
                transaction_log.append(trans)
                save_transaction_to_csv(trans)
                print(f"RESTOCKED: {quantity} {display_unit} {product_key}. New stock: {new_stock}")
            
            results.append({
                'product': product_key,
                'quantity': quantity,
                'unit': display_unit,
                'old_stock': products[product_key]["current_stock"] if not apply else old_stock,
                'new_stock': new_stock
            })
        
        else:  # sale
            if products[product_key]["current_stock"] >= quantity:
                new_stock = products[product_key]["current_stock"] - quantity
                if apply:
                    old_stock = products[product_key]["current_stock"]
                    products[product_key]["current_stock"] = new_stock
                    trans = {
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'action': 'sale',
                        'product': product_key,
                        'quantity': quantity,
                        'unit': display_unit,
                        'old_stock': old_stock,
                        'new_stock': new_stock
                    }
                    transaction_log.append(trans)
                    save_transaction_to_csv(trans)
                    print(f"SOLD: {quantity} {display_unit} {product_key}. New stock: {new_stock}")
                
                results.append({
                    'product': product_key,
                    'quantity': quantity,
                    'unit': display_unit,
                    'old_stock': products[product_key]["current_stock"] if not apply else old_stock,
                    'new_stock': new_stock
                })
            else:
                errors.append({
                    'product': product_key,
                    'quantity': quantity,
                    'unit': display_unit,
                    'available': products[product_key]["current_stock"],
                    'message': f"Not enough {product_key}. Only {products[product_key]['current_stock']} {display_unit} left."
                })
    
    # Build summary message
    if errors:
        error_msgs = [e['message'] for e in errors]
        success_msgs = [f"{r['quantity']} {r['unit']} {r['product']}" for r in results]
        message = f"⚠️ Partial {action_type}: " + ", ".join(success_msgs) if success_msgs else ""
        message += " | Errors: " + "; ".join(error_msgs)
    else:
        items_summary = ", ".join([f"{r['quantity']} {r['unit']} {r['product']}" for r in results])
        message = f"✅ {action_type.title()}: {items_summary}"
    
    return {
        'action': 'multi_' + action_type,
        'apply': bool(apply),
        'items': results,
        'errors': errors,
        'message': message,
        'count': len(results)
    }

# Enhanced text processing with measurement unit support
def process_text_command(text, apply=True):
    """Processes the transcribed text and performs inventory actions."""
    text = preprocess_text(text)
    print(f"Processing command: '{text}'")
    
    # First, try to parse multiple products
    multiple_products = parse_multiple_products(text)
    
    if multiple_products and len(multiple_products) > 1:
        # Handle multiple products
        return process_multiple_products_command(text, multiple_products, apply)
    
    # Fall back to single product parsing
    quantity, product_key, unit = parse_quantity_and_unit(text)
    
    print(f"Detected - Quantity: {quantity}, Product: {product_key}, Unit: {unit}")
    
    # If we have both quantity and product, determine action
    if quantity and product_key:
        # Check for RESTOCK keywords
        restock_keywords = ['आ गया', 'आ गए', 'आया', 'जोड़', 'डाल', 'मिला']
        restock_found = any(keyword in text for keyword in restock_keywords)
        
        # Check for SALE keywords
        sale_keywords = ['बेचा', 'बेचे', 'बिक', 'दिया', 'ग्राहक']
        sale_found = any(keyword in text for keyword in sale_keywords)

        print(f"Action detection - Restock: {restock_found}, Sale: {sale_found}")
        
        # 🆕 AUTO-CREATE: Only on RESTOCK, not on SALE
        if product_key not in products:
            if restock_found and not sale_found:
                # This is a restock of a new product - create it
                print(f"🆕 NEW PRODUCT DETECTED: '{product_key}' - Auto-creating...")
                
                # Determine unit (use detected unit or default to 'packet')
                new_unit = unit if unit else 'packet'
                
                # Create new product with smart defaults
                products[product_key] = {
                    'current_stock': 0,  # Will be set by restock
                    'threshold': max(1, int(quantity * 0.2)),  # 20% of first quantity
                    'unit': new_unit,
                    'base_unit': new_unit,
                    'price': 0  # Shopkeeper can update later
                }
                
                # Add to English name mapping (use same name for now)
                product_name_english[product_key] = product_key.title()
                
                print(f"✅ Created: {product_key} | Unit: {new_unit} | Threshold: {products[product_key]['threshold']}")
            else:
                # This is a sale/unknown action for unknown product - ERROR
                return {
                    'action': 'error',
                    'message': f"❌ Product '{product_key}' not found in inventory. Please add it first using restock."
                }
        
        # Now product definitely exists, proceed with action
        # Determine the appropriate unit for display
        display_unit = unit if unit else products[product_key]['unit']

        # RESTOCK action
        if restock_found and not sale_found:
            new_stock = products[product_key]["current_stock"] + quantity
            if apply:
                old_stock = products[product_key]["current_stock"]
                products[product_key]["current_stock"] = new_stock
                
                # 🧠 SMART THRESHOLD: Update to 20% of new stock
                new_threshold = max(1, int(new_stock * 0.2))
                products[product_key]["threshold"] = new_threshold
                print(f"🧠 Smart Threshold Updated: {product_key} → {new_threshold} (20% of {new_stock})")
                
                # Log transaction
                trans = {
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'action': 'restock',
                    'product': product_key,
                    'quantity': quantity,
                    'unit': display_unit,
                    'old_stock': old_stock,
                    'new_stock': new_stock,
                    'price': products[product_key].get('price', 0),
                    'total_amount': -(quantity * products[product_key].get('price', 0)) # Restock costs money? Or just tracking item value? Let's keep it positive for inventory value, or handle logic. Usually restock is expense. But here just logging. Let's log positive value.
                }
                # For restock, maybe we don't count it as revenue. 
                trans['total_amount'] = 0 # No revenue from restock
                
                transaction_log.append(trans)
                save_transaction_to_csv(trans)
                print(f"RESTOCKED: {quantity} {display_unit} {product_key}. New stock: {products[product_key]['current_stock']} {products[product_key]['unit']}")
            return {
                'action': 'restock',
                'apply': bool(apply),
                'product': product_key,
                'quantity': quantity,
                'unit': display_unit,
                'old_stock': products[product_key]['current_stock'] if apply else products[product_key]['current_stock'],
                'new_stock': new_stock,
                'message': f"Restock {quantity} {display_unit} {product_key} → {new_stock} {products[product_key]['unit']}"
            }

        # SALE action (default if no clear action)
        else:
            if products[product_key]["current_stock"] >= quantity:
                new_stock = products[product_key]["current_stock"] - quantity
                if apply:
                    old_stock = products[product_key]["current_stock"]
                    products[product_key]["current_stock"] = new_stock
                    # Log transaction
                    trans = {
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'action': 'sale',
                        'product': product_key,
                        'quantity': quantity,
                        'unit': display_unit,
                        'old_stock': old_stock,
                        'new_stock': new_stock,
                        'price': products[product_key].get('price', 0),
                        'total_amount': quantity * products[product_key].get('price', 0)
                    }
                    transaction_log.append(trans)
                    save_transaction_to_csv(trans)
                    print(f"SOLD: {quantity} {display_unit} {product_key}. New stock: {products[product_key]['current_stock']} {products[product_key]['unit']}")
                return {
                    'action': 'sale',
                    'apply': bool(apply),
                    'product': product_key,
                    'quantity': quantity,
                    'unit': display_unit,
                    'old_stock': products[product_key]['current_stock'] if apply else products[product_key]['current_stock'],
                    'new_stock': new_stock,
                    'message': f"Sell {quantity} {display_unit} {product_key} → {new_stock} {products[product_key]['unit']}"
                }
            else:
                print(f"Not enough stock: {products[product_key]['current_stock']} {products[product_key]['unit']} {product_key} left")
                return {
                    'action': 'error',
                    'apply': False,
                    'product': product_key,
                    'quantity': quantity,
                    'unit': display_unit,
                    'old_stock': products[product_key]['current_stock'],
                    'new_stock': products[product_key]['current_stock'],
                    'message': f"Not enough {product_key}. Only {products[product_key]['current_stock']} {products[product_key]['unit']} left."
                }
    
    # If only product found, assume it's a QUERY
    elif product_key and not quantity:
        stock = products[product_key]["current_stock"]
        unit = products[product_key]["unit"]
        print(f"STOCK CHECK: {product_key} has {stock} {unit}")
        return {
            'action': 'query',
            'apply': False,
            'product': product_key,
            'quantity': None,
            'unit': unit,
            'old_stock': stock,
            'new_stock': stock,
            'message': f"Stock of {product_key} is {stock} {unit}."
        }
    
    # If we have quantity but no product
    if quantity and not product_key:
        return {
            'action': 'unknown_product',
            'apply': False,
            'product': None,
            'quantity': quantity,
            'unit': unit,
            'message': f"❓ Understood quantity {quantity}, but didn't recognize the product. Available: {', '.join(products.keys())}"
        }
    
    return {
        'action': 'unknown',
        'apply': False,
        'message': "❓ Sorry, I didn't understand. Try: '2 kg aata beche' or '5 liters milk aa gaya' or 'kitna chawal bacha hai'"
    }


# --- Paper search MVP helpers & endpoint ---
def build_paper_search_urls(query, year_from=2022, year_to=None):
    """Return a dict of search URLs for common AI/paper sites for the given query.
    year_from: int minimum year to hint in searches (sites vary in support).
    year_to: optional max year.
    """
    q = query.strip()
    if not q:
        return {}

    # encode query
    enc = urllib.parse.quote_plus(q)
    year_range = f"{year_from}..{year_to}" if year_to else f">={year_from}"

    urls = {
        'arXiv': f'https://arxiv.org/search/?query={enc}&searchtype=all&abstracts=show&order=-announced_date_first&size=50',
        'SemanticScholar': f'https://www.semanticscholar.org/search?q={urllib.parse.quote_plus(q + " " + str(year_from))}',
        'GoogleScholar': f'https://scholar.google.com/scholar?q={enc}+{year_from}',
        'IEEE Xplore': f'https://ieeexplore.ieee.org/search/searchresult.jsp?newsearch=true&queryText={enc}',
        'ACL Anthology': f'https://aclanthology.org/search/?q={enc}',
        'Interspeech (proceedings search)': f'https://www.isca-speech.org/search/?q={enc}',
        'ArXiv API (rss-like)': f'https://export.arxiv.org/api/query?search_query=all:{urllib.parse.quote(q)}&sortBy=submittedDate&sortOrder=descending',
    }

    return urls


@app.route('/paper_search', methods=['GET'])
def paper_search():
    """Lightweight MVP: build ready-made search URLs for a query string.
    Usage: /paper_search?q=asr+error+correction
    """
    q = request.args.get('q')
    if not q:
        return jsonify({
            'error': 'Please provide q parameter',
            'examples': [
                '/paper_search?q=asr+error+correction',
                '/paper_search?q=asr+contextual+biasing'
            ]
        }), 400

    urls = build_paper_search_urls(q, year_from=2022)

    suggested_queries = [
        f"{q} error correction 2023..2025",
        f"{q} contextual biasing 2022..2025",
        f"{q} post-processing LLM 2023",
    ]

    return jsonify({
        'success': True,
        'query': q,
        'urls': urls,
        'suggested_queries': suggested_queries,
    })

# Endpoints remain the same as before
@app.route('/preprocess', methods=['POST', 'GET'])
def preprocess_demo():
    """Endpoint for testing text preprocessing with normal text input."""
    if request.method == 'POST':
        if request.is_json:
            data = request.get_json()
            text = data.get('text', '')
        else:
            text = request.form.get('text', '')
    else:
        text = request.args.get('text', '')
    
    if not text:
        return jsonify({
            'error': 'Please provide text parameter',
            'examples': [
                '/preprocess?text=2 kg aata beche',
                '/preprocess?text=5 liters milk aa gaya', 
                '/preprocess?text=kitna chawal bacha hai'
            ]
        }), 400
    
    # Read confirm flag (default apply=True for programmatic callers)
    confirm_flag = False
    if request.method == 'POST':
        if request.is_json:
            confirm_val = (data.get('confirm') if 'data' in locals() else None)
        else:
            confirm_val = request.form.get('confirm')
    else:
        confirm_val = request.args.get('confirm')
    if isinstance(confirm_val, str):
        confirm_flag = confirm_val.strip().lower() in ('1', 'true', 'yes')
    elif isinstance(confirm_val, (int, bool)):
        confirm_flag = bool(confirm_val)
    else:
        # default behavior: require confirmation (apply=False) unless explicitly confirmed
        confirm_flag = False

    # Preprocess the text
    processed_text = preprocess_text(text)
    
    # Process the command
    nlu_result = process_text_command(processed_text, apply=confirm_flag)
    
    # If not confirmed and action is valid, add to pending confirmations
    valid_actions = ['sale', 'restock', 'multi_sale', 'multi_restock']
    if not confirm_flag and nlu_result.get('action') in valid_actions:
        pending_confirmations.append({
            'id': len(pending_confirmations),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'original_text': text,
            'preprocessed_text': processed_text,
            'nlu_result': nlu_result
        })
    
    return jsonify({
        'success': True,
        'original_text': text,
        'preprocessed_text': processed_text,
        'nlu_result': nlu_result,
        'inventory': products,
        'applied': confirm_flag,
        'pending': not confirm_flag and nlu_result.get('action') in valid_actions
    })

@app.route('/test_audio', methods=['GET'])
def test_audio():
    """Endpoint for testing audio files - pure transcription only."""
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    TEST_AUDIO_DIR = os.path.join(BASE_DIR, 'test_audio_files')
    
    filename = request.args.get('file')
    if not filename:
        return jsonify({'error': 'Please provide a file parameter'}), 400
    
    filepath = os.path.join(TEST_AUDIO_DIR, filename)
    
    if not os.path.exists(filepath):
        return jsonify({'error': f'File {filename} not found.'}), 404
    
    try:
        # 1. Transcribe audio only
        raw_text = transcribe_audio_sr(filepath)
        print(f"Audio transcription: '{raw_text}'")
        
        # 2. Process the command directly (no separate preprocessing step)
        # The process_text_command function already includes preprocessing internally
        nlu_result = process_text_command(raw_text)

        # 3. Summarize and extract entities (free and local)
        summary = summarize_text(raw_text, sentences_count=3)
        entities = extract_entities(raw_text)

        return jsonify({
            'success': True,
            'filename': filename,
            'transcription': raw_text,
            'summary': summary,
            'entities': entities,
            'result': nlu_result,
            'inventory': products
        })

    except Exception as e:
        print(f"Error in test_audio: {str(e)}")
        return jsonify({'error': str(e)}), 500

def save_transaction_to_csv(transaction):
    """Save a completed transaction to CSV file"""
    file_exists = os.path.exists(TRANSACTIONS_CSV)
    
    with open(TRANSACTIONS_CSV, 'a', newline='', encoding='utf-8') as f:
        fieldnames = ['timestamp', 'action', 'product', 'quantity', 'unit', 'old_stock', 'new_stock', 'price', 'total_amount']
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        
        if not file_exists:
            writer.writeheader()
        
        writer.writerow(transaction)

def load_transactions_from_csv():
    """Load transaction history from CSV file"""
    if not os.path.exists(TRANSACTIONS_CSV):
        return []
    
    transactions = []
    with open(TRANSACTIONS_CSV, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            transactions.append(row)
    
    return transactions

@app.route('/inventory', methods=['GET'])
def get_inventory():
    return jsonify({
        'products': products,
        'english_names': product_name_english,
        'unit_names': unit_name_english
    })

@app.route('/transactions', methods=['GET'])
def get_transactions():
    """Get recent transaction log (last 50 transactions)"""
    return jsonify({
        'transactions': transaction_log[-50:][::-1],  # Last 50, most recent first
        'total_count': len(transaction_log)
    })

@app.route('/history', methods=['GET'])
def history():
    """Get all transaction history for the history view"""
    transactions = load_transactions_from_csv()
    return jsonify(transactions[::-1])  # Return as list, most recent first

@app.route('/pending_confirmations', methods=['GET'])
def get_pending_confirmations():
    """Get pending confirmations from voice input"""
    return jsonify({
        'pending': pending_confirmations,
        'count': len(pending_confirmations)
    })

@app.route('/confirm_action', methods=['POST'])
def confirm_action():
    """Confirm a pending action by ID"""
    data = request.get_json()
    action_id = data.get('id')
    
    if action_id is None:
        return jsonify({'error': 'Missing action ID'}), 400
    
    # Find the pending action
    pending = None
    for i, p in enumerate(pending_confirmations):
        if p['id'] == action_id:
            pending = pending_confirmations.pop(i)
            break
    
    if not pending:
        return jsonify({'error': 'Action not found or already processed'}), 404
    
    # Re-process with apply=True
    nlu_result = process_text_command(pending['preprocessed_text'], apply=True)
    
    return jsonify({
        'success': True,
        'result': nlu_result,
        'inventory': products
    })

@app.route('/reject_action', methods=['POST'])
def reject_action():
    """Reject a pending action by ID"""
    data = request.get_json()
    action_id = data.get('id')
    
    if action_id is None:
        return jsonify({'error': 'Missing action ID'}), 400
    
    # Find and remove the pending action
    for i, p in enumerate(pending_confirmations):
        if p['id'] == action_id:
            pending_confirmations.pop(i)
            return jsonify({'success': True, 'message': 'Action rejected'})
    
    return jsonify({'error': 'Action not found'}), 404

@app.route('/set_voice_status', methods=['POST'])
def set_voice_status():
    """Update valid voice client connection status"""
    global android_client_connected
    data = request.get_json()
    status = data.get('status')
    
    if status is not None:
        android_client_connected = bool(status)
        print(f"📡 Voice Status Updated: {'Online' if android_client_connected else 'Offline'}")
        return jsonify({'success': True, 'status': android_client_connected})
    
    return jsonify({'error': 'Missing status'}), 400

@app.route('/update_price', methods=['POST'])
def update_price():
    """Update the price of a product."""
    data = request.get_json()
    product_name = data.get('product')
    new_price = data.get('price')

    if not product_name or new_price is None:
        return jsonify({'error': 'Missing product or price'}), 400

    # Try to find by key or value
    target_key = None
    if product_name in products:
        target_key = product_name
    else:
        # Try finding by English name
        for k, v in product_name_english.items():
            if v.lower() == product_name.lower():
                target_key = k
                break
    
    if target_key:
        try:
            products[target_key]['price'] = float(new_price)
            print(f"💰 Price Updated: {target_key} -> ₹{new_price}")
            return jsonify({'success': True, 'new_price': products[target_key]['price']})
        except ValueError:
             return jsonify({'error': 'Invalid price format'}), 400
    
    return jsonify({'error': 'Product not found'}), 404

@app.route('/edit_pending', methods=['POST'])
def edit_pending():
    """Edit a pending transaction"""
    data = request.get_json()
    action_id = data.get('id')
    new_quantity = data.get('quantity')
    new_product = data.get('product')
    multi_items = data.get('multi_items')  # For multi-product transactions: [{product, quantity}, ...]
    
    if action_id is None:
        return jsonify({'error': 'Missing action ID'}), 400
    
    # Find the pending action
    for i, p in enumerate(pending_confirmations):
        if p['id'] == action_id:
            nlu = p['nlu_result']
            action = nlu.get('action', '')
            
            # Handle multi-product transactions
            if action.startswith('multi_') and multi_items:
                items = nlu.get('items', [])
                
                # Filter out removed items (those with display:none)
                valid_items = []
                for idx, new_item in enumerate(multi_items):
                    if idx < len(items):
                        new_product_key = new_item['product']
                        new_qty = float(new_item['quantity'])
                        
                        # Validate product exists
                        if new_product_key not in products:
                            continue
                        
                        # Update item
                        items[idx]['product'] = new_product_key
                        items[idx]['quantity'] = new_qty
                        items[idx]['unit'] = products[new_product_key]['unit']
                        
                        # Recalculate stock changes
                        if action == 'multi_restock':
                            items[idx]['new_stock'] = products[new_product_key]['current_stock'] + new_qty
                        elif action == 'multi_sale':
                            items[idx]['new_stock'] = products[new_product_key]['current_stock'] - new_qty
                        
                        items[idx]['old_stock'] = products[new_product_key]['current_stock']
                        valid_items.append(items[idx])
                
                # Update items list with only valid items
                nlu['items'] = valid_items
                
                # Update message
                items_summary = ", ".join([f"{item['quantity']} {item['unit']} {item['product']}" for item in valid_items])
                nlu['message'] = f"✅ {action.replace('multi_', '').title()}: {items_summary}"
                
                return jsonify({'success': True, 'updated': p})
            
            # Handle single-product transactions
            else:
                if new_quantity is not None:
                    nlu['quantity'] = float(new_quantity)
                if new_product and new_product in products:
                    # Update product
                    old_product = nlu.get('product')
                    nlu['product'] = new_product
                    nlu['unit'] = products[new_product]['unit']
                    print(f"[DEBUG] Product changed from '{old_product}' to '{new_product}'")
                
                # Recalculate stock changes
                product_key = nlu['product']
                quantity = nlu['quantity']
                
                if action == 'restock':
                    nlu['new_stock'] = products[product_key]['current_stock'] + quantity
                elif action == 'sale':
                    nlu['new_stock'] = products[product_key]['current_stock'] - quantity
                
                nlu['old_stock'] = products[product_key]['current_stock']
                nlu['message'] = f"{action.title()} {quantity} {nlu['unit']} {product_key} → {nlu['new_stock']} {products[product_key]['unit']}"
                
                return jsonify({'success': True, 'updated': p})
    
    return jsonify({'error': 'Action not found'}), 404

@app.route('/manual_entry', methods=['POST'])
def manual_entry():
    """Manually add a transaction"""
    data = request.get_json()
    product_key = data.get('product')
    quantity = data.get('quantity')
    action_type = data.get('action', 'sale')  # 'sale' or 'restock'
    
    if not product_key or not quantity:
        return jsonify({'error': 'Missing product or quantity'}), 400
    
    if product_key not in products:
        return jsonify({'error': 'Product not found'}), 404
    
    try:
        quantity = float(quantity)
    except ValueError:
        return jsonify({'error': 'Invalid quantity'}), 400
    
    # Process the transaction
    old_stock = products[product_key]['current_stock']
    unit = products[product_key]['unit']
    
    if action_type == 'restock':
        new_stock = old_stock + quantity
        products[product_key]['current_stock'] = new_stock
    else:  # sale
        if old_stock < quantity:
            return jsonify({'error': f'Insufficient stock. Only {old_stock} {unit} available'}), 400
        new_stock = old_stock - quantity
        products[product_key]['current_stock'] = new_stock
    
    # Log transaction
    transaction = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'action': action_type,
        'product': product_key,
        'quantity': quantity,
        'unit': unit,
        'old_stock': old_stock,
        'new_stock': new_stock
    }
    
    transaction_log.append(transaction)
    save_transaction_to_csv(transaction)
    
    return jsonify({
        'success': True,
        'transaction': transaction,
        'inventory': products
    })

@app.route('/export_csv', methods=['GET'])
def export_csv():
    """Export transaction history as CSV"""
    if not os.path.exists(TRANSACTIONS_CSV):
        return jsonify({'error': 'No transactions to export'}), 404
    
    return send_file(TRANSACTIONS_CSV, as_attachment=True, download_name='transactions_history.csv')

@app.route('/transaction_history', methods=['GET'])
def get_transaction_history():
    """Get all transaction history from CSV"""
    transactions = load_transactions_from_csv()
    return jsonify({
        'transactions': transactions[::-1],  # Most recent first
        'total_count': len(transactions)
    })

@app.route('/reset', methods=['GET'])
def reset_inventory():
    global products, transaction_log, pending_confirmations
    transaction_log = []  # Clear transaction log
    pending_confirmations = []  # Clear pending confirmations
    products = {
        "पारले जी": {"current_stock": 100, "threshold": 20, "unit": "पैकेट", "base_unit": "पैकेट"},
        "लेज़": {"current_stock": 50, "threshold": 15, "unit": "पैकेट", "base_unit": "पैकेट"},
        "डाबर हनी": {"current_stock": 30, "threshold": 10, "unit": "बोतल", "base_unit": "बोतल"},
        "टाटा नमक": {"current_stock": 80, "threshold": 25, "unit": "पैकेट", "base_unit": "पैकेट"},
        "कोक": {"current_stock": 40, "threshold": 12, "unit": "बोतल", "base_unit": "बोतल"},
        "साबुन": {"current_stock": 25, "threshold": 8, "unit": "पीस", "base_unit": "पीस"},
        "आटा": {"current_stock": 100, "threshold": 25, "unit": "किलो", "base_unit": "किलो"},
        "चावल": {"current_stock": 150, "threshold": 30, "unit": "किलो", "base_unit": "किलो"},
        "दाल": {"current_stock": 80, "threshold": 20, "unit": "किलो", "base_unit": "किलो"},
        "चीनी": {"current_stock": 60, "threshold": 15, "unit": "किलो", "base_unit": "किलो"},
        "तेल": {"current_stock": 50, "threshold": 12, "unit": "लीटर", "base_unit": "लीटर"},
        "दूध": {"current_stock": 40, "threshold": 10, "unit": "लीटर", "base_unit": "लीटर"},
        "चाय": {"current_stock": 5, "threshold": 2, "unit": "किलो", "base_unit": "किलो"},
    }
    return jsonify({"message": "Inventory reset", "inventory": products})

@app.route('/')
def home():
    # Serve the professional dashboard template
    template_path = os.path.join(os.path.dirname(__file__), 'dashboard_template.html')
    with open(template_path, 'r', encoding='utf-8') as f:
        return f.read()

@app.route('/old_home')
def old_home():
    # Generate the inventory table HTML (same as before)
    inventory_table = """
    <table border="1" style="border-collapse: collapse; width: 100%; margin: 20px 0; font-family: Arial, sans-serif;">
        <thead>
            <tr style="background-color: #4CAF50; color: white;">
                <th style="padding: 12px; text-align: left;">Product</th>
                <th style="padding: 12px; text-align: center;">Current Stock</th>
                <th style="padding: 12px; text-align: center;">Threshold</th>
                <th style="padding: 12px; text-align: center;">Unit</th>
                <th style="padding: 12px; text-align: center;">Status</th>
            </tr>
        </thead>
        <tbody>
    """
    
    for product, details in products.items():
        current_stock = details['current_stock']
        threshold = details['threshold']
        unit = details['unit']
        
        if current_stock <= threshold:
            status = "⚠️ LOW STOCK"
            row_color = "#FFE6E6"
        elif current_stock <= threshold * 2:
            status = "ℹ️ MEDIUM STOCK"
            row_color = "#FFF6E6"
        else:
            status = "✅ GOOD STOCK"
            row_color = "#E6FFE6"
        
        inventory_table += f"""
            <tr style="background-color: {row_color};">
                <td style="padding: 10px; font-weight: bold;">{product.title()}</td>
                <td style="padding: 10px; text-align: center; font-size: 16px;">{current_stock}</td>
                <td style="padding: 10px; text-align: center;">{threshold}</td>
                <td style="padding: 10px; text-align: center;">{unit}</td>
                <td style="padding: 10px; text-align: center; font-weight: bold;">{status}</td>
            </tr>
        """
    
    inventory_table += """
        </tbody>
    </table>
    """
    
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Voice Inventory Management System</title>
        <style>
    body {{
        font-family: 'Segoe UI', sans-serif;
        margin: 0;
        background: #eef2f6;
    }}

    header {{
        background: #111827;
        padding: 18px 30px;
        color: white;
        font-size: 22px;
        font-weight: 600;
        letter-spacing: .5px;
    }}

    .container {{
        max-width: 1300px;
        margin: 25px auto;
        background: white;
        border-radius: 12px;
        box-shadow: 0 4px 10px rgba(0,0,0,.08);
        padding: 20px 30px;
    }}

    .command-bar {{
        display: flex;
        gap: 10px;
        margin-bottom: 20px;
    }}

    .command-bar input {{
        flex: 1;
        padding: 12px;
        border-radius: 6px;
        border: 1px solid #ccc;
        font-size: 16px;
    }}

    .command-bar button {{
        padding: 12px 18px;
        border: none;
        border-radius: 6px;
        background: #2563eb;
        color: white;
        font-weight: 600;
        cursor: pointer;
    }}
    .command-bar button:hover {{ background: #1e4fd4; }}

    table {{
        width: 100%;
        border-collapse: collapse;
        margin-top: 15px;
        font-size: 15px;
    }}

    th, td {{
        padding: 12px;
        border-bottom: 1px solid #e5e7eb;
        text-align: center;
    }}

    th {{
        background: #f3f4f6;
        font-weight: 600;
        text-transform: uppercase;
        font-size: 14px;
    }}

    .status {{
        padding: 5px 10px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 13px;
    }}
    .low {{ background: #fee2e2; color: #b91c1c; }}
    .medium {{background: #fff7d6; color: #b45309; }}
    .good {{ background: #dcfce7; color: #15803d; }}

    .dashboard-layout {{
        display: grid;
        grid-template-columns: 2fr 1fr;
        gap: 25px;
        margin-top: 25px;
    }}

    #transaction-list {{
        background: #f9fafb;
        border-radius: 8px;
        padding: 10px 15px;
        height: 500px;
        overflow-y: auto;
        border: 1px solid #e5e7eb;
    }}

    .transaction-item {{
        background: white;
        border-left: 4px solid #2563eb;
        margin-bottom: 10px;
        border-radius: 4px;
        padding: 8px 12px;
        font-size: 14px;
    }}
    .transaction-item.sale {{ border-left-color: #dc2626; }}
    .transaction-item.restock {{ border-left-color: #0ea5e9; }}

    #confirm-box {{
        display:none;
        background:#fff8e1;
        padding:15px;
        border:1px solid #f0c36d;
        border-radius:8px;
        margin:15px 0;
    }}
</style>
        <script>
    async function previewAction(text) {{
        const res = await fetch('/preprocess?text=' + encodeURIComponent(text) + '&confirm=0');
        const data = await res.json();
        
        const box = document.getElementById('confirm-box');
        box.style.display = 'block';
        box.dataset.text = text;

        box.querySelector('.summary').textContent = data.nlu_result?.message || 'No action detected.';
    }}

    async function confirmAction() {{
        const box = document.getElementById('confirm-box');
        const actionId = box.dataset.actionId;
        
        if (actionId !== undefined && actionId !== '') {{
            // Confirm pending action from voice input
            await fetch('/confirm_action', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{id: parseInt(actionId)}})
            }});
        }} else {{
            // Confirm manual text input
            const text = box.dataset.text || '';
            await fetch('/preprocess?text=' + encodeURIComponent(text) + '&confirm=1');
        }}
        
        box.style.display = 'none';
        location.reload(); // refresh inventory
    }}

    async function cancelAction() {{
        const box = document.getElementById('confirm-box');
        const actionId = box.dataset.actionId;
        
        if (actionId !== undefined && actionId !== '') {{
            // Reject pending action from voice input
            await fetch('/reject_action', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{id: parseInt(actionId)}})
            }});
        }}
        
        box.style.display = 'none';
    }}

    async function loadTransactions() {{
        try {{
            const res = await fetch('/transactions');
            const data = await res.json();
            const container = document.getElementById('transaction-list');
            
            if (!data.transactions || data.transactions.length === 0) {{
                container.innerHTML = '<p style="text-align: center; color: #999; padding: 20px;">No transactions yet</p>';
                return;
            }}
            
            container.innerHTML = data.transactions.map(t => {{
                const badgeClass = t.action === 'sale' ? 'badge-sale' : 'badge-restock';
                const itemClass = t.action === 'sale' ? 'sale' : 'restock';
                const icon = t.action === 'sale' ? '📤' : '📥';
                
                return `
                    <div class="transaction-item ${{itemClass}}">
                        <div class="transaction-details">
                            <div><strong>${{icon}} ${{t.product}}</strong></div>
                            <div>${{t.quantity}} ${{t.unit}} • ${{t.old_stock}} → ${{t.new_stock}} ${{t.unit}}</div>
                            <div class="transaction-time">${{t.timestamp}}</div>
                        </div>
                        <span class="transaction-badge ${{badgeClass}}">${{t.action}}</span>
                    </div>
                `;
            }}).join('');
        }} catch (err) {{
            console.error('Failed to load transactions:', err);
        }}
    }}

    async function checkPendingConfirmations() {{
        try {{
            const res = await fetch('/pending_confirmations');
            const data = await res.json();
            
            if (data.pending && data.pending.length > 0) {{
                // Show the first pending confirmation
                const pending = data.pending[0];
                const box = document.getElementById('confirm-box');
                box.style.display = 'block';
                box.dataset.actionId = pending.id;
                box.dataset.text = '';  // Clear manual text
                
                const nluResult = pending.nlu_result;
                let detailsHtml = '';
                
                // Check if it's a multi-product action
                if (nluResult.action && nluResult.action.startsWith('multi_')) {{
                    const items = nluResult.items || [];
                    const itemsList = items.map(item => 
                        `<li>${{item.quantity}} ${{item.unit}} ${{item.product}} (${{item.old_stock}} → ${{item.new_stock}})</li>`
                    ).join('');
                    detailsHtml = `
                        <strong>🎤 Voice Input:</strong> "${{pending.original_text}}"<br>
                        <strong>Action:</strong> ${{nluResult.action.replace('multi_', '').toUpperCase()}} (${{items.length}} items)<br>
                        <ul style="margin: 8px 0; padding-left: 20px;">${{itemsList}}</ul>
                    `;
                }} else {{
                    const message = nluResult?.message || 'Voice command detected';
                    detailsHtml = `
                        <strong>🎤 Voice Input:</strong> "${{pending.original_text}}"<br>
                        <strong>Action:</strong> ${{message}}
                    `;
                }}
                
                box.querySelector('.summary').innerHTML = detailsHtml;
            }}
        }} catch (err) {{
            console.error('Failed to check pending confirmations:', err);
        }}
    }}

    async function refreshDashboard() {{
        await loadTransactions();
        await checkPendingConfirmations();
        // Update inventory table by reloading page (simple approach)
        // For smoother UX, could fetch /inventory and update table dynamically
    }}

    document.addEventListener('DOMContentLoaded', () => {{
        // Load transactions and check for pending confirmations on page load
        loadTransactions();
        checkPendingConfirmations();
        
        // Auto-refresh every 3 seconds (faster response for voice input)
        setInterval(refreshDashboard, 3000);

        // Make example links preview instead of executing directly
        document.querySelectorAll('.examples a').forEach(a => {{
            a.addEventListener('click', (e) => {{
                e.preventDefault();
                const url = new URL(a.href, location.origin);
                const text = url.searchParams.get('text') || '';
                previewAction(text);
            }});
        }});

        // Free form input preview
        const form = document.getElementById('freeform');
        if (form) {{
            form.addEventListener('submit', (e) => {{
                e.preventDefault();
                const text = document.getElementById('freeform-text').value.trim();
                if (text) previewAction(text);
            }});
        }}
    }});
</script>
    </head>
    <body>
        <header>🛒 QuickStock Inventory Dashboard</header>

<div class="container">

    <!-- Command Input -->
    <div class="command-bar">
        <input id="freeform-text" type="text" placeholder="🎙️ Speak or type: '5 किलो आटा बेचा'">
        <button onclick="previewAction(document.getElementById('freeform-text').value)">Submit</button>
    </div>

    <!-- Confirm Box -->
    <div id="confirm-box">
        <div style="font-weight:bold; margin-bottom:8px;">Confirm Action</div>
        <div class="summary" style="margin-bottom:10px;"></div>
        <button onclick="confirmAction()" style="margin-right:8px;">✅ Confirm</button>
        <button onclick="cancelAction()">❌ Cancel</button>
    </div>

    <!-- Dashboard -->
    <div class="dashboard-layout">
        
        <!-- Inventory Table -->
        <div>
            <h2>📦 Inventory</h2>
            {inventory_table}
        </div>

        <!-- Transaction Log -->
        <div>
            <h2>📜 Recent Transactions</h2>
            <div id="transaction-list">Loading...</div>
        </div>
    </div>
</div>

    </body>
    </html>
    """

@app.route('/history', methods=['GET'])
def get_history():
    """Returns the transaction history from CSV."""
    if not os.path.exists(TRANSACTIONS_CSV):
        return jsonify([])
    
    history_data = []
    try:
        with open(TRANSACTIONS_CSV, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Add English name if available
                p_name = row.get('product', '')
                if p_name in product_name_english:
                    row['product_en'] = product_name_english[p_name]
                else:
                    # Try reverse lookup if needed or just use Hindi
                    row['product_en'] = p_name
                history_data.append(row)
        
        # Return newest first
        return jsonify(list(reversed(history_data)))
    except Exception as e:
        print(f"Error reading history: {e}")
        return jsonify([])

@app.route('/set_client_status', methods=['POST'])
def set_client_status():
    global android_client_connected
    data = request.json
    if data and 'connected' in data:
        android_client_connected = data['connected']
        status = "CONNECTED" if android_client_connected else "DISCONNECTED"
        print(f"📱 Android Client Status: {status}")
        return jsonify({"status": "updated", "connected": android_client_connected})
    return jsonify({"error": "Invalid data"}), 400

@app.route('/dashboard_stats', methods=['GET'])
def get_dashboard_stats():
    """Returns aggregated stats: Revenue, Low Stock, Pending, Client Status, and Revenue History."""
    
    today_str = date.today().isoformat() # YYYY-MM-DD
    revenue_by_date = {} # {'2026-02-16': 384.0, ...}
    
    if os.path.exists(TRANSACTIONS_CSV):
        try:
            with open(TRANSACTIONS_CSV, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Timestamp format: 2025-11-06 20:29:04 or 16/02/2026
                    ts = row.get('timestamp', '')
                    if not ts: continue
                    
                    # Improve date parsing to handle potentially different formats if manual edits happen
                    # But standard format is YYYY-MM-DD HH:MM:SS
                    try: 
                        date_part = ts.split(' ')[0] 
                        # If date is like 16/02/2026 (DD/MM/YYYY) -> convert to YYYY-MM-DD for consistency?
                        # Actually standard python strftime is YYYY-MM-DD. 
                        # Let's trust the format is consistent YYYY-MM-DD.
                    except: continue

                    if row.get('action') == 'sale':
                        amount = 0.0
                        # STRICT: Only use 'total_amount' from CSV
                        if 'total_amount' in row and row['total_amount']:
                             try:
                                 # Remove currency symbol if accidentally saved
                                 val_str = str(row['total_amount']).replace('₹', '').replace(',', '').strip()
                                 amount = float(val_str)
                             except: 
                                 amount = 0.0
                        
                        # Add to daily sum
                        revenue_by_date[date_part] = revenue_by_date.get(date_part, 0) + amount
        except Exception as e:
            print(f"Error calc revenue: {e}")

    today_revenue = revenue_by_date.get(today_str, 0)

    # 2. Low Stock Count
    low_stock_count = 0
    for p in products.values():
        if p['current_stock'] <= p['threshold']:
            low_stock_count += 1
            
    # 3. Pending Count
    pending_count = len(pending_confirmations)
    
    return jsonify({
        "today_revenue": round(today_revenue, 2),
        "revenue_history": revenue_by_date,
        "low_stock_count": low_stock_count,
        "pending_count": pending_count,
        "voice_active": android_client_connected
    })

if __name__ == '__main__':
    # Try different ports if 5001 is busy
    port = 5001
    print(f"\n🎯 Voice Inventory Management System with Measurement Units")
    print(f"📍 Now supports: kg, g, liters, ml, packets, bottles, pieces")
    print(f"📍 Access: http://localhost:{port}")
    print(f"\n🌟 Try these measurement commands:")
    print(f"   • http://localhost:{port}/preprocess?text=2 kg aata beche")
    print(f"   • http://localhost:{port}/preprocess?text=5 liters milk aa gaya")
    print(f"   • http://localhost:{port}/preprocess?text=500 g sugar beche\n")
    print(f"Type Ctrl+C to stop the server\n")
    
    try:
        app.run(host='0.0.0.0', port=port, debug=True, use_reloader=False)
    except OSError:
        print(f"Port {port} in use, trying {port+1}...")
        app.run(host='0.0.0.0', port=port+1, debug=True, use_reloader=False)