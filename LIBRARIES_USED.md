# Libraries and Tools Used in QuickStock™

This document provides a comprehensive list of the libraries, frameworks, and tools used in the **QuickStock™** project, along with their purpose and implementation details.

---

## 1. Core Web & API Framework

| Library | What it is | Where it's used | Why it's used | How it's used |
| :--- | :--- | :--- | :--- | :--- |
| **Flask** | A lightweight Python web framework. | `app.py` | To serve the dashboard UI and provide the backend API for inventory management. | Defines routes like `/inventory`, `/preprocess`, and `/confirm_action` to handle system logic. |
| **Requests** | A simple HTTP library for Python. | `app.py`, `voice_stream_file.py` | To allow the voice processing script to communicate with the main Flask server. | `requests.post()` is used to send transcribed text from the voice client to the backend for NLU processing. |

---

## 2. Speech Processing & Voice Intelligence

| Library | What it is | Where it's used | Why it's used | How it's used |
| :--- | :--- | :--- | :--- | :--- |
| **Vosk** | An offline open-source STT toolkit. | `voice_stream_file.py` | For continuous, real-time, and offline speech-to-text (Hindi & English). | Loads `Model` and `KaldiRecognizer` to process PCM audio streams via sockets. |
| **SpeechRecognition** | A wrapper for various STT engines. | `app.py` | Used as a secondary or alternative transcription method for audio files. | `recognizer.recognize_google(audio, language="en-IN")` processes recorded WAV/MP3 files. |
| **PyAudio** | Python bindings for PortAudio. | `requirements.txt` | To capture live audio from the microphone (often used by STT engines). | Typically used as the backend driver for capturing real-time voice input. |

---

## 3. Natural Language Processing (NLP)

| Library | What it is | Where it's used | Why it's used | How it's used |
| :--- | :--- | :--- | :--- | :--- |
| **spaCy** | Advanced NLP library. | `app.py` | For Named Entity Recognition (NER) to extract numbers, dates, and products. | Loads the `en_core_web_sm` model to identify parts of speech and entities in transcribed text. |
| **Indic NLP Library** | NLP for Indian languages. | `app.py` | To handle specific linguistic variations in Hindi (normalization). | `IndicNormalizerFactory` standardizes different spellings or diacritics in Hindi inputs. |
| **Indic Transliteration** | Script conversion tool. | `voice_stream_file.py`, `app.py` | To convert Hindi (Devanagari) to Roman script for easier NLU processing. | The `transliterate` function converts "चीनी" to "chiinii" for the internal pattern matchers. |
| **Deep Translator** | Language translation tool. | `voice_stream_file.py` | To bridge the gap between Hindi voice input and English backend logic. | Uses `GoogleTranslator` and `MyMemoryTranslator` to translate text between En and Hi. |
| **Difflib** | Standard library for sequences. | `app.py` | For fuzzy string matching of product names (handling typos). | `get_close_matches()` finds the closest inventory item (e.g., "लेज़" matches "लेस"). |

---

## 4. Analytics & AI Utilities

| Library | What it is | Where it's used | Why it's used | How it's used |
| :--- | :--- | :--- | :--- | :--- |
| **Sumy** | Text summarization tool. | `app.py` | To generate concise summaries of long transaction logs or notes. | Uses the `LexRankSummarizer` to extract key sentences from plaintext data. |
| **NLTK** | Natural Language Toolkit. | `requirements.txt` | Basic text tokenization and linguistic utilities. | Often used by `Sumy` or standard NLP pre-processors for splitting sentences/words. |
| **Regex (re)** | Pattern matching module. | Entire project | To extract quantities, units, and intent via structured patterns. | Custom regular expressions parse strings like "2 किलो आटा" into `(2, "kg", "Aata")`. |

---

## 5. Frontend Visualization

| Library | What it is | Where it's used | Why it's used | How it's used |
| :--- | :--- | :--- | :--- | :--- |
| **Chart.js** | JavaScript charting library. | `dashboard_template.html` | To visualize stock levels, sales trends, and predicted revenue. | Renders interactive line graphs (`salesChart`) and doughnut charts (`categoryChart`). |
| **Remix Icon** | Icon library. | `dashboard_template.html` | To provide modern, premium UI icons for the dashboard sidebar and cards. | Integrated via CSS CDN to show icons for "Inventory", "Voice", and "Orders". |
| **Google Fonts** | Hosted font service. | `dashboard_template.html` | To give the dashboard a premium, modern aesthetic using the "Outfit" typeface. | Imported via `<link>` tags to replace default system fonts. |

---

## 6. Pre-trained Models & Resources

The following models are essential dependencies stored within the project:

*   **vosk-model-en-in-0.5**: Optimized model for Indian English accents.
*   **vosk-model-hi-0.22**: High-accuracy model for Hindi speech.
*   **en_core_web_sm**: SpaCy's English language model for tokenization and NER.
