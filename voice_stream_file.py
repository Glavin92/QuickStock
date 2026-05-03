import socket
import time
import json
import os
import sys
import re
import csv
from datetime import datetime
from vosk import Model, KaldiRecognizer
try:
    import requests
    _has_requests = True
except Exception:
    _has_requests = False

# 🔵 BULK RESTOCK MODE
BULK_MODE_ACTIVE = False  # Global state: Is bulk mode on?
BULK_START_KEYWORDS = ['inventory setup start', 'स्टॉक शुरू करो', 'setup start', 'stock start']
BULK_STOP_KEYWORDS = ['setup stop', 'स्टॉक बंद करो', 'stock stop', 'setup band']
bulk_items_added = []  # Track items added in bulk mode
bulk_start_time = None  # Track when bulk mode started
BULK_RESTOCK_CSV = "bulk_restock_history.csv"  # CSV file for bulk sessions

try:
    from indic_transliteration.sanscript import transliterate, Devanagari, ITRANS
    _has_translit = True
except Exception:
    _has_translit = False

try:
    from deep_translator import GoogleTranslator, MyMemoryTranslator
    _has_translator = True
except Exception:
    _has_translator = False

def to_latin(text):
    if not text:
        return text
    if _has_translit and re.search(r"[\u0900-\u097F]", text):
        try:
            return transliterate(text, Devanagari, ITRANS)
        except Exception:
            return text
    return text

def to_english(text):
    if not text:
        return text
    if _has_translator:
        try:
            # Force Hindi as source; Google can return unchanged text if detection fails
            translated = GoogleTranslator(source='hi', target='en').translate(text)
            if translated and translated.strip() and translated.strip() != text.strip():
                return translated
            # Fallback to MyMemory if Google returned same text or empty
            fallback = MyMemoryTranslator(source='hi', target='en').translate(text)
            if fallback and fallback.strip():
                print("ℹ️ Translation fallback used (MyMemory)")
                return fallback
        except Exception as _e:
            try:
                fallback = MyMemoryTranslator(source='hi', target='en').translate(text)
                if fallback and fallback.strip():
                    print("ℹ️ Translation fallback used (MyMemory)")
                    return fallback
            except Exception:
                pass
    return text

def to_hindi(text):
    if not text:
        return text
    if _has_translator:
        try:
            translated = GoogleTranslator(source='en', target='hi').translate(text)
            if translated and translated.strip():
                return translated
            fallback = MyMemoryTranslator(source='en', target='hi').translate(text)
            if fallback and fallback.strip():
                print("ℹ️ Hindi translation fallback used (MyMemory)")
                return fallback
        except Exception:
            try:
                fallback = MyMemoryTranslator(source='en', target='hi').translate(text)
                if fallback and fallback.strip():
                    print("ℹ️ Hindi translation fallback used (MyMemory)")
                    return fallback
            except Exception:
                pass
    return text

HOST = "0.0.0.0"
PORT = 6000

print("⏳ Loading dual-language STT models (Hindi + English)...")

# Resolve model paths robustly
_CWD = os.path.dirname(os.path.abspath(__file__))

# Hindi model candidates
_hindi_candidates = [
    os.path.join(_CWD, "vosk-model-hi-0.22"),
    os.path.join(_CWD, "vosk-model-small-hi-0.22", "vosk-model-small-hi-0.22"),
    os.path.join(_CWD, "vosk-model-small-hi"),
]

# English model candidates (common Vosk English models)
_english_candidates = [
    os.path.join(_CWD, "vosk-model-small-en-in-0.15"),
    os.path.join(_CWD, "vosk-model-en-in-0.5"),
    os.path.join(_CWD, "vosk-model-en-in-0.22-lgraph"),
    os.path.join(_CWD, "vosk-model-small-en-in-0.15", "vosk-model-small-en-in-0.15"),
    os.path.join(_CWD, "vosk-model-en-in-0.22", "vosk-model-en-in-0.22"),
]

hindi_model_path = None
for d in _hindi_candidates:
    if os.path.isdir(d):
        hindi_model_path = d
        break

english_model_path = None
for d in _english_candidates:
    if os.path.isdir(d):
        english_model_path = d
        break

if hindi_model_path is None:
    raise FileNotFoundError(
        "Hindi Vosk model not found. Expected one of: " + "; ".join(_hindi_candidates)
    )
PRODUCTS = [
    "सर्फ एक्सेल",
    "रिन",
    "टाइड",
    "कोलगेट",
    "कोलिन",
    "हार्पिक",
    "पारले जी",
    "मैगी",
    "चीनी",
    "अमूल",
    "रेड लेबल",
    "ब्रू"
]

if english_model_path is None:
    print("⚠️  Warning: English model not found. Only Hindi recognition will work.")
    print("   Expected one of: " + "; ".join(_english_candidates))
    print("   You can download from: https://alphacephei.com/vosk/models")
    model_hi = Model(hindi_model_path)
    recognizer_hi = KaldiRecognizer(model_hi, 16000, json.dumps(PRODUCTS))
    recognizer_en = None
else:
    print(f"✅ Loaded Hindi model: {hindi_model_path}")
    print(f"✅ Loaded English model: {english_model_path}")
    model_hi = Model(hindi_model_path)
    model_en = Model(english_model_path)
    recognizer_hi = KaldiRecognizer(model_hi, 16000, json.dumps(PRODUCTS))
    recognizer_en = KaldiRecognizer(model_en, 16000, json.dumps(PRODUCTS))

_last_partial_hi = ""
_last_partial_en = ""
_english_word_buffer = set()


def _post_json_with_retry(url, payload, timeout_seconds=10, retries=1, backoff_seconds=0.5):
    """POST JSON with a small retry/backoff.

    This keeps voice streaming responsive when the Flask app/DB is briefly slow.
    """
    last_err = None
    for attempt in range(retries + 1):
        try:
            return requests.post(url, json=payload, timeout=timeout_seconds)
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(backoff_seconds)
    raise last_err

def process_pcm_streaming(pcm):
    global _last_partial_hi, _last_partial_en
    results = {"final_hi": None, "final_en": None, "partial_hi": None, "partial_en": None}
    
    # Process through Hindi recognizer
    if recognizer_hi.AcceptWaveform(pcm):
        res = json.loads(recognizer_hi.Result())
        final_hi = (res.get("text") or "").strip()
        if final_hi:
            results["final_hi"] = final_hi
    else:
        res = json.loads(recognizer_hi.PartialResult())
        partial_hi = (res.get("partial") or "").strip()
        if partial_hi and partial_hi != _last_partial_hi:
            _last_partial_hi = partial_hi
            results["partial_hi"] = partial_hi
    
    # Process through English recognizer (if available)
    if recognizer_en:
        if recognizer_en.AcceptWaveform(pcm):
            res = json.loads(recognizer_en.Result())
            final_en = (res.get("text") or "").strip()
            if final_en:
                results["final_en"] = final_en
        else:
            res = json.loads(recognizer_en.PartialResult())
            partial_en = (res.get("partial") or "").strip()
            if partial_en and partial_en != _last_partial_en:
                _last_partial_en = partial_en
                results["partial_en"] = partial_en
    
    # Print partials
    if results["partial_hi"]:
        print("🗣 Partial (Hindi):", to_latin(results["partial_hi"]))
    if results["partial_en"]:
        print("🗣 Partial (English):", results["partial_en"])
    
    # Handle final results - combine or prioritize
    if results["final_hi"] or results["final_en"]:
        global BULK_MODE_ACTIVE, bulk_items_added

        # IMPORTANT: reset english token buffer per utterance so it doesn't leak across commands
        _english_word_buffer.clear()
        
        final_hi = results["final_hi"]
        final_en = results["final_en"]
        
        # If both detected, prefer the longer/more confident one, or combine
        if final_hi and final_en:
            print("✅ Final (Hindi):", to_latin(final_hi))
            print("✅ Final (English):", final_en)
            # Prefer Hindi if it's longer (more confident), otherwise use English
            if len(final_hi.split()) >= len(final_en.split()):
                chosen = final_hi
                chosen_lang = "hi"
            else:
                chosen = final_en
                chosen_lang = "en"
        elif final_hi:
            chosen = final_hi
            chosen_lang = "hi"
            print("✅ Final (Hindi):", to_latin(final_hi))
        else:
            chosen = final_en
            chosen_lang = "en"
            print("✅ Final (English):", final_en)
        
        # 🔵 BULK MODE DETECTION
        chosen_lower = chosen.lower()
        
        # Check for START keywords
        is_bulk_start = any(keyword in chosen_lower for keyword in BULK_START_KEYWORDS)
        if is_bulk_start:
            global bulk_start_time
            BULK_MODE_ACTIVE = True
            bulk_items_added = []
            bulk_start_time = datetime.now()
            print(f"🔵 BULK RESTOCK MODE ACTIVATED at {bulk_start_time.strftime('%H:%M:%S')} - Say items to add, then say 'SETUP STOP'")
            return {
                "final": chosen,
                "bulk_mode": "started",
                "message": "Bulk mode activated"
            }
        
        # Check for STOP keywords
        is_bulk_stop = any(keyword in chosen_lower for keyword in BULK_STOP_KEYWORDS)
        if is_bulk_stop:
            if BULK_MODE_ACTIVE:
                BULK_MODE_ACTIVE = False
                count = len(bulk_items_added)
                end_time = datetime.now()
                print(f"💚 BULK MODE COMPLETE - {count} items added: {bulk_items_added}")
                
                # Save to CSV
                try:
                    file_exists = os.path.exists(BULK_RESTOCK_CSV)
                    with open(BULK_RESTOCK_CSV, mode='a', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        if not file_exists:
                            writer.writerow(['timestamp', 'date', 'time', 'items_count', 'items_list'])
                        
                        items_str = '; '.join(bulk_items_added)
                        writer.writerow([
                            bulk_start_time.strftime('%Y-%m-%d %H:%M:%S'),
                            bulk_start_time.strftime('%Y-%m-%d'),
                            bulk_start_time.strftime('%H:%M:%S'),
                            count,
                            items_str
                        ])
                    print(f"📝 Bulk session saved to {BULK_RESTOCK_CSV}")
                except Exception as e:
                    print(f"❌ Failed to save bulk session: {e}")
                
                items_copy = bulk_items_added.copy()
                bulk_items_added = []
                bulk_start_time = None
                return {
                    "final": chosen,
                    "bulk_mode": "stopped",
                    "items_added": items_copy,
                    "count": count
                }
            else:
                print("⚠️ Bulk mode was not active")
                return {"final": chosen, "ignored": True}
        
        # If in bulk mode, force restock behavior
        if BULK_MODE_ACTIVE:
            print(f"🔵 BULK MODE ACTIVE - Processing as restock")
            # Force add restock keyword if not present
            if not any(kw in chosen_lower for kw in ['आ गया', 'आया', 'aa gaya']):
                final_hi = final_hi + " आ गया" if final_hi else chosen + " aa gaya"
                print(f"🔵 Modified for restock: {final_hi}")
        
        # Build merged Hinglish:
        # - If Hindi was chosen, avoid appending random English partials (causes garbled output)
        # - If English was chosen, keep it as-is
        merged_hinglish = to_latin(chosen) if chosen_lang == "hi" else chosen

        # Translate to pure English for display if needed
        english = to_english(chosen) if chosen_lang == "hi" else chosen
        if chosen_lang == "hi":
            print("🌐 English:", english)

        # Send merged Hinglish to Flask app for processing
        try:
            if _has_requests and final_hi:
                url = os.environ.get("APP_PROCESS_URL", "http://127.0.0.1:5001/preprocess")
                resp = _post_json_with_retry(
                    url,
                    {"text": final_hi},
                    timeout_seconds=float(os.environ.get("APP_PROCESS_TIMEOUT", "10")),
                    retries=int(os.environ.get("APP_PROCESS_RETRIES", "1")),
                    backoff_seconds=float(os.environ.get("APP_PROCESS_BACKOFF", "0.5")),
                )
                if resp.ok:
                    data = resp.json()
                    result = data.get("nlu_result") or data
                    print("🧠 App processed:", result)
                    
                    # Track items in bulk mode
                    if BULK_MODE_ACTIVE and result.get('action') == 'restock':
                        product = result.get('product', 'unknown')
                        quantity = result.get('quantity', 0)
                        bulk_items_added.append(f"{quantity} {product}")
                        print(f"📦 Bulk item #{len(bulk_items_added)}: {quantity} {product}")
                else:
                    print("❌ App response:", resp.status_code, (resp.text or "")[:200])
            elif not _has_requests:
                print("⚠️ 'requests' not installed; cannot POST to Flask app.")
        except Exception as e:
            print("❌ Failed to send to Flask app:", e)

        return {"final": chosen, "final_hi": final_hi, "final_en": final_en, "english": english, "merged_hinglish": merged_hinglish, "partial": None}
    
    return {"final": None, "final_hi": None, "final_en": None, "partial": None}

def update_status(status):
    """Notify app server about client connection status"""
    try:
        if _has_requests:
            url = os.environ.get("APP_STATUS_URL", "http://127.0.0.1:5001/set_voice_status")
            try:
                requests.post(url, json={"status": status}, timeout=1)
            except Exception:
                pass # Fail silently
    except Exception:
        pass

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((HOST, PORT))
server.listen(1)

print(f"\n🎤 Voice Stream (continuous) running on {HOST}:{PORT}\n")

while True:
    conn, addr = server.accept()
    print(f"✅ Android connected: {addr}")
    update_status(True) # Notify connected
    try:
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            out = process_pcm_streaming(chunk)
            if out.get("final"):
                # Send merged Hinglish (Hindi transliteration + English words) to client
                merged = out.get("merged_hinglish") or to_latin(out.get("final") or "")
                conn.send(((merged or "") + "\n").encode())
    except Exception as e:
        print("❌ Client disconnected or error:", e)
    finally:
        conn.close()
        update_status(False) # Notify disconnected
        print("🔌 Waiting for next client...\n")
