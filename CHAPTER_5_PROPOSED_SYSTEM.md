# Chapter 5: Proposed System - Implementation Plan and Experimental Setup

## 5.1 Experimental Setup

### 5.1.1 System Architecture Overview

The QuickStock Voice Inventory Management System is implemented as a client-server architecture with the following components:

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────┐
│  Android/Mobile │ ──TCP──>│  Voice Stream    │ ──HTTP─>│   Flask Web     │
│  Audio Client   │  6000   │  Server (Vosk)   │  5000   │   Application   │
└─────────────────┘         └──────────────────┘         └─────────────────┘
                                     │                            │
                                     │                            │
                                     v                            v
                            ┌─────────────────┐         ┌─────────────────┐
                            │  Hindi + English│         │  CSV Database   │
                            │  Vosk Models    │         │  + In-Memory    │
                            └─────────────────┘         └─────────────────┘
```

### 5.1.2 Hardware Requirements

| Component | Specification | Purpose |
|-----------|--------------|---------|
| **Processor** | Intel Core i5 or equivalent (2.0 GHz+) | Running ML models and web server |
| **RAM** | 8 GB minimum, 16 GB recommended | Loading Vosk models and processing |
| **Storage** | 5 GB free space | Vosk models (2 GB), transaction logs |
| **Microphone** | Any standard microphone or smartphone | Audio input capture |
| **Network** | Local network or localhost | Client-server communication |

### 5.1.3 Software Requirements

| Software | Version | Purpose |
|----------|---------|---------|
| **Python** | 3.8+ | Core runtime environment |
| **Flask** | 2.0+ | Web framework for REST API |
| **Vosk** | 0.3.45+ | Offline speech recognition |
| **spaCy** | 3.0+ | NLP and entity recognition |
| **Node.js** | Optional | For advanced frontend features |
| **Web Browser** | Chrome/Firefox (latest) | Dashboard interface |

### 5.1.4 Python Dependencies

```python
# Core Dependencies
Flask==2.3.0
vosk==0.3.45
SpeechRecognition==3.10.0
requests==2.31.0

# NLP & Text Processing
spacy==3.5.0
sumy==0.11.0
nltk==3.8.1
indic-nlp-library==0.92
indic-transliteration==2.3.0

# Translation
deep-translator==1.11.4

# Data Processing
pandas==2.0.0
numpy==1.24.0
```

---

## 5.2 Details of Database and Input Systems

### 5.2.1 Database Structure

#### **Primary Storage: In-Memory Dictionary (Python Dict)**

```python
products = {
    "पारले जी": {
        "current_stock": 100,
        "threshold": 20,
        "unit": "पैकेट",
        "base_unit": "पैकेट"
    },
    "लेज़": {
        "current_stock": 50,
        "threshold": 15,
        "unit": "पैकेट",
        "base_unit": "पैकेट"
    },
    # ... 12 products total
}
```

**Characteristics:**
- **Type:** Hash table (O(1) access)
- **Size:** 12 products initially
- **Persistence:** Session-based (resets on restart)
- **Advantages:** Fast read/write, simple structure

#### **Secondary Storage: CSV File (Persistent)**

**File:** `transactions_history.csv`

**Schema:**
```csv
timestamp,action,product,quantity,unit,old_stock,new_stock
2025-11-06 20:30:15,sale,पारले जी,2,पैकेट,100,98
2025-11-06 20:31:22,restock,आटा,10,किलो,90,100
```

**Fields:**
- `timestamp`: DateTime (YYYY-MM-DD HH:MM:SS)
- `action`: Enum (sale, restock)
- `product`: String (product name in Hindi)
- `quantity`: Float (amount transacted)
- `unit`: String (measurement unit)
- `old_stock`: Float (stock before transaction)
- `new_stock`: Float (stock after transaction)

**Characteristics:**
- **Format:** CSV (UTF-8 encoded)
- **Persistence:** Permanent
- **Growth:** Append-only, unbounded
- **Access Pattern:** Sequential read, append write

#### **Tertiary Storage: Pending Confirmations Queue**

```python
pending_confirmations = [
    {
        'id': 0,
        'timestamp': '2025-11-06 20:30:00',
        'original_text': '2 lays और 3 parle g',
        'preprocessed_text': '2 lays aur 3 parle g',
        'nlu_result': {
            'action': 'multi_sale',
            'items': [...],
            'message': '...'
        }
    }
]
```

**Characteristics:**
- **Type:** List (FIFO queue)
- **Persistence:** Session-based
- **Purpose:** Voice input confirmation workflow

---

### 5.2.2 Input Data Sources

#### **1. Voice Input (Primary)**

**Source:** Android smartphone or PC microphone  
**Format:** PCM audio stream (16-bit, 16kHz, mono)  
**Protocol:** TCP socket (port 6000)  
**Processing Pipeline:**
```
Microphone → PCM Stream → Vosk STT → Hindi/English Text → NLU → Transaction
```

**Sample Input:**
- "दो किलो आटा बेचा" (2 kg flour sold)
- "5 parle g और 3 lays आ गए" (5 parle g and 3 lays restocked)
- "kitna chawal bacha hai" (how much rice is left)

#### **2. Manual Text Input (Secondary)**

**Source:** Web dashboard form  
**Format:** JSON via HTTP POST  
**Endpoint:** `/manual_entry`

**Sample Request:**
```json
{
    "product": "पारले जी",
    "quantity": 5,
    "action": "sale"
}
```

#### **3. Voice Command Input (Tertiary)**

**Source:** Web dashboard text box  
**Format:** Text string via HTTP GET/POST  
**Endpoint:** `/preprocess`

**Sample Request:**
```
GET /preprocess?text=2%20kg%20aata%20beche&confirm=0
```

---

### 5.2.3 Selected Data (Test Dataset)

#### **Product Inventory (12 Items)**

| Product (Hindi) | Product (English) | Initial Stock | Unit | Threshold |
|-----------------|-------------------|---------------|------|-----------|
| पारले जी | Parle-G Biscuits | 100 | पैकेट | 20 |
| लेज़ | Lays Chips | 50 | पैकेट | 15 |
| डाबर हनी | Dabur Honey | 30 | बोतल | 10 |
| टाटा नमक | Tata Salt | 80 | पैकेट | 25 |
| कोक | Coca-Cola | 40 | बोतल | 12 |
| साबुन | Soap | 25 | पीस | 8 |
| आटा | Wheat Flour | 100 | किलो | 25 |
| चावल | Rice | 150 | किलो | 30 |
| दाल | Lentils | 80 | किलो | 20 |
| चीनी | Sugar | 60 | किलो | 15 |
| तेल | Oil | 50 | लीटर | 12 |
| दूध | Milk | 40 | लीटर | 10 |

**Data Characteristics:**
- **Domain:** Common grocery items in Indian retail
- **Language:** Hindi (Devanagari script)
- **Units:** Mixed (kg, liters, packets, bottles, pieces)
- **Stock Range:** 25-150 units
- **Threshold Range:** 8-30 units

#### **Test Voice Commands (Sample Dataset)**

```
1. "दो किलो आटा बेचा" → Sale: 2 kg flour
2. "5 parle g आ गए" → Restock: 5 packets Parle-G
3. "3 lays और 2 coke बेचे" → Multi-sale: 3 Lays + 2 Coke
4. "kitna chawal bacha hai" → Query: Rice stock
5. "10 लीटर तेल आ गया" → Restock: 10 liters oil
```

---

## 5.3 Performance Evaluation Parameters

### 5.3.1 Speech Recognition Metrics

| Metric | Formula | Target | Measurement Method |
|--------|---------|--------|-------------------|
| **Word Error Rate (WER)** | `(S + D + I) / N × 100` | < 15% | Manual transcription comparison |
| **Recognition Latency** | Time from audio end to text output | < 2 seconds | Timestamp logging |
| **Language Detection Accuracy** | Correct language / Total utterances | > 90% | Manual verification |

**Where:**
- S = Substitutions
- D = Deletions
- I = Insertions
- N = Total words in reference

**Test Methodology:**
1. Record 50 voice commands (25 Hindi, 25 Hinglish)
2. Compare Vosk output with manual transcription
3. Calculate WER for each language
4. Measure end-to-end latency

---

### 5.3.2 NLU Performance Metrics

| Metric | Description | Target | Validation Method |
|--------|-------------|--------|-------------------|
| **Intent Classification Accuracy** | Correct action detection (sale/restock/query) | > 95% | Test set of 100 commands |
| **Entity Extraction F1-Score** | Product, quantity, unit extraction | > 90% | Precision + Recall |
| **Multi-Product Parsing Success** | Correctly split multi-item commands | > 85% | 30 multi-product test cases |
| **Unit Conversion Accuracy** | Correct unit normalization | 100% | Automated unit tests |

**Test Cases:**
```python
# Test Case 1: Intent Classification
Input: "5 किलो चावल बेचा"
Expected: action='sale', product='चावल', quantity=5, unit='किलो'

# Test Case 2: Multi-Product
Input: "2 lays और 3 parle g"
Expected: [(2, 'लेज़', 'पैकेट'), (3, 'पारले जी', 'पैकेट')]

# Test Case 3: Unit Conversion
Input: "500 gram चीनी"
Expected: quantity=0.5, unit='किलो'
```

---

### 5.3.3 System Performance Metrics

| Metric | Target | Measurement Tool |
|--------|--------|------------------|
| **API Response Time** | < 500ms (95th percentile) | Flask logging + time.time() |
| **Concurrent Users** | 10+ simultaneous connections | Load testing (Apache Bench) |
| **Memory Usage** | < 2 GB RAM | psutil monitoring |
| **CPU Usage** | < 70% average | System monitor |
| **Transaction Throughput** | 100+ transactions/minute | Stress testing |

**Load Testing Command:**
```bash
ab -n 1000 -c 10 http://localhost:5000/preprocess?text=test
```

---

### 5.3.4 User Experience Metrics

| Metric | Target | Collection Method |
|--------|--------|-------------------|
| **Confirmation Accuracy** | User confirms 90%+ of suggestions | Dashboard analytics |
| **Edit Rate** | < 10% of transactions edited | Edit button click tracking |
| **Average Transaction Time** | < 10 seconds (voice to confirm) | End-to-end timing |
| **User Satisfaction** | 4/5 stars average | Post-use survey |

---

### 5.3.5 Data Quality Metrics

| Metric | Description | Validation |
|--------|-------------|------------|
| **CSV Data Integrity** | No corrupted/missing fields | Automated validation script |
| **Stock Consistency** | No negative stock values | Assertion checks |
| **Timestamp Accuracy** | Correct chronological order | Sequential validation |
| **UTF-8 Encoding** | Proper Hindi character storage | File encoding check |

---

## 5.4 Special Requirements

### 5.4.1 External Resources

#### **1. Vosk Speech Models (Offline)**

**Download Required:**
- **Hindi Model:** `vosk-model-hi-0.22` (1.8 GB)
  - Source: https://alphacephei.com/vosk/models
  - Path: `./vosk-model-hi-0.22/`
  
- **English Model:** `vosk-model-small-en-in-0.15` (40 MB)
  - Source: https://alphacephei.com/vosk/models
  - Path: `./vosk-model-small-en-in-0.15/`

**Why Offline Models:**
- No internet dependency
- Privacy (no data sent to cloud)
- Low latency
- No API costs

#### **2. spaCy Language Model**

**Download Command:**
```bash
python -m spacy download en_core_web_sm
```

**Size:** 12 MB  
**Purpose:** Entity recognition and NLP

#### **3. Translation API (Optional)**

**Service:** Google Translate API (via deep-translator)  
**Requirement:** Internet connection  
**Fallback:** MyMemory Translator (free, no API key)  
**Usage:** Hindi ↔ English translation for display

---

### 5.4.2 Hardware Requirements (Detailed)

#### **Development Environment**

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **CPU** | Intel i5 8th Gen / Ryzen 5 | Intel i7 10th Gen / Ryzen 7 |
| **RAM** | 8 GB | 16 GB |
| **Storage** | 256 GB SSD | 512 GB SSD |
| **GPU** | Not required | Optional (for model training) |
| **Microphone** | Built-in | External USB mic |
| **Network** | WiFi | Ethernet (for stability) |

#### **Production Environment (Small Shop)**

| Component | Specification |
|-----------|---------------|
| **Device** | Raspberry Pi 4 (4GB) or budget PC |
| **Storage** | 32 GB SD card / 128 GB SSD |
| **Display** | Any monitor/tablet (1024×768+) |
| **Input** | Smartphone (for voice) + touchscreen |
| **Network** | Local WiFi router |

---

### 5.4.3 Cloud Requirements (Optional Scaling)

**For Future Cloud Deployment:**

| Service | Provider | Purpose | Estimated Cost |
|---------|----------|---------|----------------|
| **Compute** | AWS EC2 t3.medium | Flask app hosting | $30/month |
| **Storage** | AWS S3 | Transaction backup | $5/month |
| **Database** | AWS RDS (PostgreSQL) | Persistent storage | $15/month |
| **CDN** | CloudFlare | Dashboard delivery | Free tier |
| **Domain** | Namecheap | quickstock.in | $10/year |

**Total Estimated Cost:** $50/month for cloud deployment

**Current Setup:** $0/month (fully local, no cloud dependency)

---

### 5.4.4 Network Requirements

| Parameter | Specification |
|-----------|---------------|
| **Voice Stream Port** | TCP 6000 (local) |
| **Web Dashboard Port** | HTTP 5000 (local) |
| **Bandwidth** | 10 Mbps (local network) |
| **Latency** | < 50ms (LAN) |
| **Firewall** | Allow ports 5000, 6000 |

---

### 5.4.5 Security Requirements

| Aspect | Implementation |
|--------|----------------|
| **Authentication** | Not implemented (local use only) |
| **Data Encryption** | Not required (local network) |
| **Backup** | Manual CSV export |
| **Access Control** | Physical device access only |
| **HTTPS** | Not required (localhost) |

**Future Security Enhancements:**
- User authentication (Flask-Login)
- HTTPS with SSL certificates
- Database encryption
- Role-based access control

---

## 5.5 Implementation Plan for Next Semester

### 5.5.1 Term I Timeline (Weeks 1-8)

#### **Week 1-2: System Enhancement**
- [ ] Implement user authentication system
- [ ] Add multi-user support with roles (admin, cashier)
- [ ] Create user management dashboard
- [ ] **Deliverable:** User authentication module

#### **Week 3-4: Database Migration**
- [ ] Migrate from CSV to SQLite/PostgreSQL
- [ ] Implement database schema with relationships
- [ ] Add data backup and restore functionality
- [ ] Create database migration scripts
- [ ] **Deliverable:** Persistent database system

#### **Week 5-6: Advanced Features**
- [ ] Implement barcode scanning integration
- [ ] Add product image support
- [ ] Create sales analytics dashboard
- [ ] Implement low-stock alerts (SMS/Email)
- [ ] **Deliverable:** Enhanced feature set

#### **Week 7-8: Testing & Documentation**
- [ ] Comprehensive unit testing (80%+ coverage)
- [ ] Integration testing
- [ ] Performance benchmarking
- [ ] User acceptance testing (UAT)
- [ ] **Deliverable:** Test report and documentation

---

### 5.5.2 Term II Timeline (Weeks 9-16)

#### **Week 9-10: Mobile Application**
- [ ] Develop Android app for voice input
- [ ] Implement offline mode
- [ ] Add push notifications
- [ ] **Deliverable:** Android APK

#### **Week 11-12: Cloud Deployment**
- [ ] Set up AWS/Azure infrastructure
- [ ] Configure CI/CD pipeline
- [ ] Implement auto-scaling
- [ ] Set up monitoring (CloudWatch/Azure Monitor)
- [ ] **Deliverable:** Cloud-hosted system

#### **Week 13-14: Advanced NLU**
- [ ] Fine-tune Vosk models with custom data
- [ ] Implement context-aware conversations
- [ ] Add support for more languages (Tamil, Telugu)
- [ ] Improve multi-product parsing accuracy
- [ ] **Deliverable:** Enhanced NLU engine

#### **Week 15-16: Final Integration & Deployment**
- [ ] End-to-end system testing
- [ ] Performance optimization
- [ ] Security audit
- [ ] Pilot deployment in 2-3 shops
- [ ] **Deliverable:** Production-ready system

---

### 5.5.3 Gantt Chart (Term I + Term II)

```
Task                        | W1 | W2 | W3 | W4 | W5 | W6 | W7 | W8 | W9 | W10| W11| W12| W13| W14| W15| W16|
----------------------------|----|----|----|----|----|----|----|----|----|----|----|----|----|----|----|----|
User Authentication         |████|████|    |    |    |    |    |    |    |    |    |    |    |    |    |    |
Database Migration          |    |    |████|████|    |    |    |    |    |    |    |    |    |    |    |    |
Advanced Features           |    |    |    |    |████|████|    |    |    |    |    |    |    |    |    |    |
Testing & Documentation     |    |    |    |    |    |    |████|████|    |    |    |    |    |    |    |    |
Mobile App Development      |    |    |    |    |    |    |    |    |████|████|    |    |    |    |    |    |
Cloud Deployment            |    |    |    |    |    |    |    |    |    |    |████|████|    |    |    |    |
Advanced NLU                |    |    |    |    |    |    |    |    |    |    |    |    |████|████|    |    |
Final Integration           |    |    |    |    |    |    |    |    |    |    |    |    |    |    |████|████|
```

---

### 5.5.4 Milestones & Deliverables

| Milestone | Week | Deliverable | Success Criteria |
|-----------|------|-------------|------------------|
| **M1: Enhanced System** | Week 4 | User auth + Database | Multi-user login working |
| **M2: Feature Complete** | Week 8 | All features + Tests | 80%+ test coverage |
| **M3: Mobile Ready** | Week 12 | Android app + Cloud | App on Play Store |
| **M4: Production Launch** | Week 16 | Deployed system | 3 shops using system |

---

### 5.5.5 Risk Management

| Risk | Probability | Impact | Mitigation Strategy |
|------|-------------|--------|---------------------|
| **Vosk model accuracy issues** | Medium | High | Collect custom training data, fine-tune models |
| **Cloud cost overrun** | Low | Medium | Use auto-scaling, set budget alerts |
| **Database migration bugs** | Medium | High | Extensive testing, rollback plan |
| **User adoption resistance** | High | High | Training sessions, demo videos |
| **Network connectivity issues** | Medium | Medium | Implement offline mode |

---

### 5.5.6 Resource Allocation

#### **Team Structure (Recommended)**

| Role | Responsibility | Time Allocation |
|------|----------------|-----------------|
| **Backend Developer** | Flask API, Database | 40% |
| **Frontend Developer** | Dashboard, Mobile app | 30% |
| **ML Engineer** | NLU, Voice processing | 20% |
| **QA Engineer** | Testing, Documentation | 10% |

#### **Budget Estimate**

| Item | Cost (INR) |
|------|------------|
| Cloud hosting (6 months) | ₹18,000 |
| Domain + SSL | ₹1,000 |
| Testing devices | ₹5,000 |
| Miscellaneous | ₹2,000 |
| **Total** | **₹26,000** |

---

### 5.5.7 Success Metrics (End of Term II)

| Metric | Target |
|--------|--------|
| **System Uptime** | 99.5% |
| **Active Users** | 5+ shops |
| **Transactions/Day** | 500+ |
| **Voice Recognition Accuracy** | 92%+ |
| **User Satisfaction** | 4.5/5 stars |
| **Response Time** | < 300ms (p95) |

---

## 5.6 Project Management Tools

### 5.6.1 Recommended Tools

| Tool | Purpose | Link |
|------|---------|------|
| **GitHub Projects** | Task tracking, Kanban board | github.com |
| **Jira** | Agile project management | atlassian.com/jira |
| **Trello** | Simple task management | trello.com |
| **Notion** | Documentation, wiki | notion.so |
| **Slack** | Team communication | slack.com |
| **Git** | Version control | git-scm.com |

### 5.6.2 Development Workflow

```
Feature Request → GitHub Issue → Branch → Development → Testing → PR → Review → Merge → Deploy
```

### 5.6.3 CI/CD Pipeline

```
Code Push → GitHub Actions → Unit Tests → Build → Docker Image → Deploy to Staging → Manual Approval → Production
```

---

## 5.7 Conclusion

The proposed system implementation plan provides a comprehensive roadmap for developing a production-ready voice-based inventory management system. The experimental setup is designed to be cost-effective, scalable, and suitable for small retail businesses in India. The timeline ensures systematic development with clear milestones and deliverables for both terms.

**Key Highlights:**
- ✅ Fully local setup (no cloud dependency initially)
- ✅ Offline speech recognition (privacy-focused)
- ✅ Multi-language support (Hindi, English, Hinglish)
- ✅ Comprehensive testing framework
- ✅ Clear migration path to cloud
- ✅ Realistic timeline with risk mitigation
