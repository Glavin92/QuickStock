# QuickStock™: AI-Powered Inventory & Billing with Voice Intelligence


## 🚀 Overview

**QuickStock™** is a state-of-the-art inventory management and billing system designed specifically for the modern Indian retail landscape. By leveraging **Voice Intelligence (STT)** and **Natural Language Understanding (NLU)**, it allows shopkeepers to manage stock and process bills using natural speech in **English, Hindi, and Hinglish**.

This project bridges the gap between traditional manual record-keeping and high-tech retail automation, providing a seamless, "hands-free" experience that reduces transaction time and minimizes human error.

---

## ✨ Key Features

- **🎙️ Real-time Bilingual Voice Commands**: Manage inventory using voice in Hindi, English, or a mix of both (Hinglish). Powered by **Vosk ASR**.
- **📊 Interactive Analytics Dashboard**: Visualize sales trends, stock levels, and revenue metrics with high-performance charts (**Chart.js**).
- **🧠 Smart NLU Engine**: Automatically extracts products, quantities, and units from natural speech using **spaCy NER** and custom Regex patterns.
- **📱 Omnichannel Notifications**:
  - **WhatsApp Integration**: Automated restock alerts and bill confirmations via Facebook Graph API.
  - **SMS OTP**: Secure login using Fast2SMS for mobile-first authentication.
- **🛡️ Enterprise-Grade Security**: JWT-based authentication, rate limiting, and encrypted session management.
- **📍 Location-Based Intelligence**: Find nearby wholesale partners and shops using **PostGIS** spatial queries.
- **📑 Automated Summarization**: Generate concise daily transaction summaries using the **LexRank** algorithm.

---

## 🛠️ Technology Stack

### Backend
- **Core**: Python 3.10+ / Flask
- **Real-time**: Flask-SocketIO (Eventlet)
- **Database**: PostgreSQL with PostGIS extensions
- **Security**: Flask-JWT-Extended, Flask-Limiter, Cryptography

### AI & NLP
- **Speech-to-Text**: Vosk (Offline HMM+DNN models)
- **Natural Language**: spaCy (NER), NLTK, Indic NLP Library
- **Translation**: Deep Translator (Google & MyMemory)
- **Matching**: Difflib (Ratcliff-Obershelp fuzzy matching)
- **Summarization**: Sumy (LexRank summarizer)

### Frontend
- **Design**: Vanilla CSS3 (Modern Glassmorphism Aesthetic)
- **Logic**: ES6+ JavaScript
- **Visuals**: Chart.js, Remix Icons, Google Fonts (Outfit)

---

## 🏗️ Engineering & Algorithms

QuickStock™ implements several advanced algorithms to ensure high accuracy and performance:

1.  **Vosk STT (Kaldi-based)**: Uses Hidden Markov Models (HMM) and Deep Neural Networks (DNN) for offline speech recognition.
2.  **Hinglish Merging Logic**: A confidence-based selection algorithm that merges Hindi and English tokens from dual-recognizer streams.
3.  **Hindi Number Word Parsing**: A recursive descent parser that converts phrases like *"दो सौ पचास"* to `250` in real-time.
4.  **LexRank Summarization**: A graph-based ranking algorithm (similar to Google's PageRank) to extract key transaction insights.
5.  **ASR Error Correction**: Persistent N-gram fuzzy matching to correct common speech recognition errors against the product database.

---

## 📂 Project Structure

```text
├── app.py                   # Main Flask application & NLU logic
├── voice_stream_file.py     # Real-time Voice/STT processing client
├── static/                  # CSS, JS, and UI assets
├── templates/               # Responsive HTML5 templates
├── tools/                   # Utility scripts for DB and migration
├── models/                  # Vosk language models (Hi/En-IN)
├── ALGORITHMS_USED.md       # Detailed technical documentation
└── LIBRARIES_USED.md        # Dependency breakdown
```

---

## 🚦 Getting Started

### Prerequisites
- Python 3.10+
- Docker & Docker Compose
- Vosk Models (`vosk-model-en-in-0.5`, `vosk-model-hi-0.22`)

### 🐳 Database Setup (Docker)

QuickStock uses **PostGIS** for location-based analytics. You can quickly spin up a database instance using the included `docker-compose.yml`:

```bash
docker-compose up -d
```

### Configuration
Create a `.env` file and add your database URL:
```env
DATABASE_URL=postgresql://postgres:postgres_password@localhost:5432/quickstock
```

### Installation & Initialization

1.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    python -m spacy download en_core_web_sm
    ```

2.  **Initialize Database Schema**:
    ```bash
    python setup_db.py
    python migrate_to_db.py
    ```

3.  **Run the application**:
    ```bash
    python app.py
    ```

---
Developed by **Glavin** | © 2026 QuickStock™
