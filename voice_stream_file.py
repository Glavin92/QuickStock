import socket
import time
import json
import os
import sys
import re
from vosk import Model, KaldiRecognizer
try:
    import requests
    _has_requests = True
except Exception:
    _has_requests = False

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
                # collect english words from final
                for w in re.findall(r"[A-Za-z][A-Za-z'\-]*", final_en):
                    _english_word_buffer.add(w)
        else:
            res = json.loads(recognizer_en.PartialResult())
            partial_en = (res.get("partial") or "").strip()
            if partial_en and partial_en != _last_partial_en:
                _last_partial_en = partial_en
                results["partial_en"] = partial_en
            # collect english words from partial
            for w in re.findall(r"[A-Za-z][A-Za-z'\-]*", partial_en):
                _english_word_buffer.add(w)
    
    # Print partials
    if results["partial_hi"]:
        print("🗣 Partial (Hindi):", to_latin(results["partial_hi"]))
    if results["partial_en"]:
        print("🗣 Partial (English):", results["partial_en"])
    
    # Handle final results - combine or prioritize
    if results["final_hi"] or results["final_en"]:
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
        
        # Build merged Hinglish: Hindi (transliterated) + detected English tokens
        merged_hinglish = to_latin(chosen) if chosen_lang == "hi" else chosen
        if _english_word_buffer:
            # append any english tokens not already present
            present = set(re.findall(r"[A-Za-z][A-Za-z'\-]*", merged_hinglish))
            new_words = [w for w in _english_word_buffer if w not in present]
            if new_words:
                merged_hinglish = (merged_hinglish + " " + " ".join(new_words)).strip()
                print("🌐 Merged Hinglish:", merged_hinglish)

        # Translate to pure English for display if needed
        english = to_english(chosen) if chosen_lang == "hi" else chosen
        if chosen_lang == "hi":
            print("🌐 English:", english)

        # Send merged Hinglish to Flask app for processing
        try:
            if _has_requests and final_hi:
                url = os.environ.get("APP_PROCESS_URL", "http://127.0.0.1:5000/preprocess")
                resp = requests.post(url, json={"text": final_hi}, timeout=3)
                if resp.ok:
                    data = resp.json()
                    result = data.get("nlu_result") or data
                    print("🧠 App processed:", result)
                else:
                    print("❌ App response:", resp.status_code, (resp.text or "")[:200])
            elif not _has_requests:
                print("⚠️ 'requests' not installed; cannot POST to Flask app.")
        except Exception as e:
            print("❌ Failed to send to Flask app:", e)

        return {"final": chosen, "final_hi": final_hi, "final_en": final_en, "english": english, "merged_hinglish": merged_hinglish, "partial": None}
    
    return {"final": None, "final_hi": None, "final_en": None, "partial": None}

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((HOST, PORT))
server.listen(1)

print(f"\n🎤 Voice Stream (continuous) running on {HOST}:{PORT}\n")

while True:
    conn, addr = server.accept()
    print(f"✅ Android connected: {addr}")
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
        print("🔌 Waiting for next client...\n")
