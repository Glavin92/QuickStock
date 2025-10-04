from flask import Flask, request, jsonify
import os
import re
import json
import speech_recognition as sr

app = Flask(__name__)

# Create uploads directory if it doesn't exist
os.makedirs('./test_audio_files', exist_ok=True)

# Enhanced database with measurement units and base units
products = {
    "parle g": {"current_stock": 100, "threshold": 20, "unit": "packets", "base_unit": "packets"},
    "lays": {"current_stock": 50, "threshold": 15, "unit": "packets", "base_unit": "packets"},
    "dabur honey": {"current_stock": 30, "threshold": 10, "unit": "bottles", "base_unit": "bottles"},
    "tata salt": {"current_stock": 80, "threshold": 25, "unit": "packets", "base_unit": "packets"},
    "coke": {"current_stock": 40, "threshold": 12, "unit": "bottles", "base_unit": "bottles"},
    "soap": {"current_stock": 25, "threshold": 8, "unit": "pieces", "base_unit": "pieces"},
    
    # Items with weight/volume measurements
    "aata": {"current_stock": 100, "threshold": 25, "unit": "kg", "base_unit": "kg"},  # flour
    "chawal": {"current_stock": 150, "threshold": 30, "unit": "kg", "base_unit": "kg"}, # rice
    "dal": {"current_stock": 80, "threshold": 20, "unit": "kg", "base_unit": "kg"},     # lentils
    "sugar": {"current_stock": 60, "threshold": 15, "unit": "kg", "base_unit": "kg"},   # sugar
    "oil": {"current_stock": 50, "threshold": 12, "unit": "liters", "base_unit": "liters"}, # oil
    "milk": {"current_stock": 40, "threshold": 10, "unit": "liters", "base_unit": "liters"}, # milk
    "tea": {"current_stock": 5, "threshold": 2, "unit": "kg", "base_unit": "kg"},       # tea leaves
}

# Measurement unit conversions (to base units)
unit_conversions = {
    'kg': 1,
    'kilo': 1,
    'kilogram': 1,
    'grams': 0.001,
    'gram': 0.001,
    'g': 0.001,
    'gm': 0.001,
    
    'liters': 1,
    'liter': 1,
    'l': 1,
    'ml': 0.001,
    'milliliter': 0.001,
    
    'packets': 1,
    'packet': 1,
    'pkt': 1,
    
    'bottles': 1,
    'bottle': 1,
    
    'pieces': 1,
    'piece': 1,
    'pcs': 1,
}

# Text preprocessing functions
def preprocess_text(text):
    """Preprocess the input text for better NLU understanding."""
    if not text:
        return ""
    
    print(f"Original text: '{text}'")
    
    # Convert to lowercase
    text = text.lower().strip()
    
    # Remove extra whitespace
    text = ' '.join(text.split())
    
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
    
    # Remove common filler words
    filler_words = ['please', 'ji', 'hey', 'hello', 'okay', 'ok', 'toh', 'to', 'the', 'a', 'of']
    words = text.split()
    words = [word for word in words if word not in filler_words]
    text = ' '.join(words)
    
    print(f"Preprocessed text: '{text}'")
    return text

# Enhanced helper function for fuzzy matching product names
def find_product(product_name):
    """Finds a product by fuzzy name matching."""
    product_name = product_name.lower().strip()
    
    # Exact match
    if product_name in products:
        return product_name
    
    # Partial match
    for known_product in products.keys():
        if product_name in known_product or known_product in product_name:
            return known_product
    
    # Common Hindi product name mappings
    hindi_to_english = {
        'atta': 'aata', 'flour': 'aata', 'maida': 'aata',
        'rice': 'chawal', 'chawal': 'chawal', 'chawal': 'chawal',
        'daal': 'dal', 'lentils': 'dal', 'pulses': 'dal',
        'salt': 'tata salt', 'namak': 'tata salt',
        'honey': 'dabur honey', 'shahad': 'dabur honey',
        'cheeni': 'sugar', 'sugar': 'sugar', 'shakar': 'sugar',
        'tel': 'oil', 'oil': 'oil', 'vegetable oil': 'oil',
        'doodh': 'milk', 'milk': 'milk',
        'chai': 'tea', 'tea': 'tea', 'tea leaves': 'tea',
    }
    
    if product_name in hindi_to_english:
        return hindi_to_english[product_name]
    
    return None

def parse_quantity_and_unit(text):
    """Parse quantity and unit from text, converting to base units."""
    # Patterns for different quantity formats
    patterns = [
        r'(\d+(?:\.\d+)?)\s*(kg|kilo|gram|g|gm|liters?|l|ml|packets?|pkt|bottles?|pieces?|pcs)\s+(\w+(?:\s+\w+)*)',  # "2 kg aata"
        r'(\d+(?:\.\d+)?)\s+(\w+(?:\s+\w+)*)',  # "2 aata" (default unit)
        r'(\w+(?:\s+\w+)*)\s+(\d+(?:\.\d+)?)\s*(kg|kilo|gram|g|gm|liters?|l|ml|packets?|pkt|bottles?|pieces?|pcs)',  # "aata 2 kg"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            if len(match.groups()) == 3:
                quantity = float(match.group(1))
                unit = match.group(2).lower()
                product_text = match.group(3)
            else:
                quantity = float(match.group(1))
                product_text = match.group(2)
                unit = None  # Will use product's default unit
            
            product_key = find_product(product_text)
            
            if product_key:
                # If unit is specified, convert to product's base unit
                if unit and unit in unit_conversions:
                    base_quantity = quantity * unit_conversions[unit]
                    actual_quantity = base_quantity / unit_conversions[products[product_key]['base_unit']]
                    return actual_quantity, product_key, unit
                else:
                    # Use product's default unit
                    return quantity, product_key, products[product_key]['unit']
    
    # Fallback: simple number and product detection
    words = text.split()
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
            print("🎤 Listening to audio...")
            audio = recognizer.record(source)
        text = recognizer.recognize_google(audio, language="en-IN")
        return text
    except sr.UnknownValueError:
        print("❌ Could not understand audio")
        return ""
    except sr.RequestError as e:
        print(f"⚠️ Could not request results from Google Speech Recognition; {e}")
        return ""

# Enhanced text processing with measurement unit support
def process_text_command(text):
    """Processes the transcribed text and performs inventory actions."""
    text = preprocess_text(text)
    print(f"Processing command: '{text}'")
    
    # Parse quantity, product, and unit
    quantity, product_key, unit = parse_quantity_and_unit(text)
    
    print(f"Detected - Quantity: {quantity}, Product: {product_key}, Unit: {unit}")
    
    # If we have both quantity and product, determine action
    if quantity and product_key:
        # Determine the appropriate unit for display
        display_unit = unit if unit else products[product_key]['unit']
        
        # Check for RESTOCK keywords
        restock_keywords = ['aa gaya', 'aa gaye', 'aaya', 'aaye', 'add', 'restock', 'daal', 'jod', 'mil', 'aa']
        restock_found = any(keyword in text for keyword in restock_keywords)
        
        # Check for SALE keywords
        sale_keywords = ['beche', 'bechi', 'bik', 'sold', 'liya', 'de', 'customer', 'bech']
        sale_found = any(keyword in text for keyword in sale_keywords)
        
        print(f"Action detection - Restock: {restock_found}, Sale: {sale_found}")
        
        # RESTOCK action
        if restock_found and not sale_found:
            products[product_key]["current_stock"] += quantity
            print(f"✅ RESTOCKED: {quantity} {display_unit} {product_key}. New stock: {products[product_key]['current_stock']} {products[product_key]['unit']}")
            return f"✅ Restocked {quantity} {display_unit} {product_key}. New stock: {products[product_key]['current_stock']} {products[product_key]['unit']}"
        
        # SALE action (default if no clear action)
        else:
            if products[product_key]["current_stock"] >= quantity:
                products[product_key]["current_stock"] -= quantity
                print(f"✅ SOLD: {quantity} {display_unit} {product_key}. New stock: {products[product_key]['current_stock']} {products[product_key]['unit']}")
                return f"✅ Sold {quantity} {display_unit} {product_key}. New stock: {products[product_key]['current_stock']} {products[product_key]['unit']}"
            else:
                print(f"❌ Not enough stock: {products[product_key]['current_stock']} {products[product_key]['unit']} {product_key} left")
                return f"❌ Not enough {product_key}. Only {products[product_key]['current_stock']} {products[product_key]['unit']} left."
    
    # If only product found, assume it's a QUERY
    elif product_key and not quantity:
        stock = products[product_key]["current_stock"]
        unit = products[product_key]["unit"]
        print(f"✅ STOCK CHECK: {product_key} has {stock} {unit}")
        return f"📊 Stock of {product_key} is {stock} {unit}."
    
    # If we have quantity but no product
    if quantity and not product_key:
        return f"❓ I understood quantity {quantity}, but didn't recognize the product. Available products: {', '.join(products.keys())}"
    
    return "❓ Sorry, I didn't understand. Try: '2 kg aata beche' or '5 liters milk aa gaya' or 'kitna chawal bacha hai'"

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
    
    # Preprocess the text
    processed_text = preprocess_text(text)
    
    # Process the command
    nlu_result = process_text_command(processed_text)
    
    return jsonify({
        'success': True,
        'original_text': text,
        'preprocessed_text': processed_text,
        'nlu_result': nlu_result,
        'inventory': products
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
        print(f"🎤 Audio transcription: '{raw_text}'")
        
        # 2. Process the command directly (no separate preprocessing step)
        # The process_text_command function already includes preprocessing internally
        nlu_result = process_text_command(raw_text)

        return jsonify({
            'success': True,
            'filename': filename,
            'transcription': raw_text,
            'result': nlu_result,
            'inventory': products
        })

    except Exception as e:
        print(f"❌ Error in test_audio: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/inventory', methods=['GET'])
def get_inventory():
    return jsonify(products)

@app.route('/reset', methods=['GET'])
def reset_inventory():
    global products
    products = {
        "parle g": {"current_stock": 100, "threshold": 20, "unit": "packets", "base_unit": "packets"},
        "lays": {"current_stock": 50, "threshold": 15, "unit": "packets", "base_unit": "packets"},
        "dabur honey": {"current_stock": 30, "threshold": 10, "unit": "bottles", "base_unit": "bottles"},
        "tata salt": {"current_stock": 80, "threshold": 25, "unit": "packets", "base_unit": "packets"},
        "coke": {"current_stock": 40, "threshold": 12, "unit": "bottles", "base_unit": "bottles"},
        "soap": {"current_stock": 25, "threshold": 8, "unit": "pieces", "base_unit": "pieces"},
        "aata": {"current_stock": 100, "threshold": 25, "unit": "kg", "base_unit": "kg"},
        "chawal": {"current_stock": 150, "threshold": 30, "unit": "kg", "base_unit": "kg"},
        "dal": {"current_stock": 80, "threshold": 20, "unit": "kg", "base_unit": "kg"},
        "sugar": {"current_stock": 60, "threshold": 15, "unit": "kg", "base_unit": "kg"},
        "oil": {"current_stock": 50, "threshold": 12, "unit": "liters", "base_unit": "liters"},
        "milk": {"current_stock": 40, "threshold": 10, "unit": "liters", "base_unit": "liters"},
        "tea": {"current_stock": 5, "threshold": 2, "unit": "kg", "base_unit": "kg"},
    }
    return jsonify({"message": "Inventory reset", "inventory": products})

@app.route('/')
def home():
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
                font-family: Arial, sans-serif;
                margin: 20px;
                background-color: #f5f5f5;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
                background: white;
                padding: 20px;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }}
            h1, h2, h3 {{
                color: #2c3e50;
            }}
            .examples {{
                background: #f0f8ff;
                padding: 15px;
                border-radius: 5px;
                margin: 15px 0;
                border-left: 4px solid #4CAF50;
            }}
            .product-category {{
                background: #e8f5e8;
                padding: 10px;
                margin: 10px 0;
                border-radius: 5px;
            }}
            .examples-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 15px;
                margin: 15px 0;
            }}
            .example-group {{
                background: white;
                padding: 15px;
                border-radius: 5px;
                border: 1px solid #ddd;
            }}
            .examples a {{
                color: #2c3e50;
                text-decoration: none;
                display: block;
                padding: 5px 0;
            }}
            .examples a:hover {{
                text-decoration: underline;
                background-color: #e6f7ff;
                padding-left: 5px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Voice Inventory Management System</h1>
            <h2>📊 Current Inventory Status</h2>
            {inventory_table}
            
            <h2>🎯 Examples for All Product Types</h2>
            <div class="examples">
                <div class="examples-grid">
                    
                    <!-- Weight-based Products (kg/g) -->
                    <div class="example-group">
                        <h3>⚖️ Weight-based Products (kg/g)</h3>
                        <div class="product-category">
                            <strong>Aata (Flour):</strong>
                            <ul>
                                <li><a href="/preprocess?text=2 kg aata beche">2 kg aata beche</a></li>
                                <li><a href="/preprocess?text=5 kg aata aa gaya">5 kg aata aa gaya</a></li>
                                <li><a href="/preprocess?text=kitna aata bacha hai">kitna aata bacha hai</a></li>
                            </ul>
                        </div>
                        <div class="product-category">
                            <strong>Chawal (Rice):</strong>
                            <ul>
                                <li><a href="/preprocess?text=3 kg chawal bik gaya">3 kg chawal bik gaya</a></li>
                                <li><a href="/preprocess?text=10 kg chawal aaya">10 kg chawal aaya</a></li>
                                <li><a href="/preprocess?text=chawal ka stock bataye">chawal ka stock bataye</a></li>
                            </ul>
                        </div>
                        <div class="product-category">
                            <strong>Dal (Lentils):</strong>
                            <ul>
                                <li><a href="/preprocess?text=1 kg dal beche">1 kg dal beche</a></li>
                                <li><a href="/preprocess?text=2 kg dal aa gaye">2 kg dal aa gaye</a></li>
                                <li><a href="/preprocess?text=dal kitna bacha">dal kitna bacha</a></li>
                            </ul>
                        </div>
                        <div class="product-category">
                            <strong>Sugar & Tea:</strong>
                            <ul>
                                <li><a href="/preprocess?text=500 g sugar sold">500 g sugar sold</a></li>
                                <li><a href="/preprocess?text=250 g tea add karo">250 g tea add karo</a></li>
                                <li><a href="/preprocess?text=sugar ka stock kya hai">sugar ka stock kya hai</a></li>
                            </ul>
                        </div>
                    </div>
                    
                    <!-- Volume-based Products (liters/ml) -->
                    <div class="example-group">
                        <h3>💧 Volume-based Products (liters/ml)</h3>
                        <div class="product-category">
                            <strong>Milk:</strong>
                            <ul>
                                <li><a href="/preprocess?text=1 liter milk bik gaya">1 liter milk bik gaya</a></li>
                                <li><a href="/preprocess?text=5 liters milk aaya">5 liters milk aaya</a></li>
                                <li><a href="/preprocess?text=how much milk is left">how much milk is left</a></li>
                            </ul>
                        </div>
                        <div class="product-category">
                            <strong>Oil:</strong>
                            <ul>
                                <li><a href="/preprocess?text=500 ml oil beche">500 ml oil beche</a></li>
                                <li><a href="/preprocess?text=10 liters oil aa gaye">10 liters oil aa gaye</a></li>
                                <li><a href="/preprocess?text=oil ka stock check karo">oil ka stock check karo</a></li>
                            </ul>
                        </div>
                    </div>
                    
                    <!-- Packaged Products (packets/bottles) -->
                    <div class="example-group">
                        <h3>📦 Packaged Products (packets/bottles)</h3>
                        <div class="product-category">
                            <strong>Parle-G & Lays:</strong>
                            <ul>
                                <li><a href="/preprocess?text=2 parle g beche">2 parle g beche</a></li>
                                <li><a href="/preprocess?text=10 lays packets aa gaye">10 lays packets aa gaye</a></li>
                                <li><a href="/preprocess?text=kitna parle g bacha hai">kitna parle g bacha hai</a></li>
                            </ul>
                        </div>
                        <div class="product-category">
                            <strong>Beverages:</strong>
                            <ul>
                                <li><a href="/preprocess?text=3 coke beche">3 coke beche</a></li>
                                <li><a href="/preprocess?text=12 coke bottles add karo">12 coke bottles add karo</a></li>
                                <li><a href="/preprocess?text=coke ka stock kya hai">coke ka stock kya hai</a></li>
                            </ul>
                        </div>
                        <div class="product-category">
                            <strong>Dabur Honey & Tata Salt:</strong>
                            <ul>
                                <li><a href="/preprocess?text=1 dabur honey sold">1 dabur honey sold</a></li>
                                <li><a href="/preprocess?text=5 tata salt packets aaye">5 tata salt packets aaye</a></li>
                                <li><a href="/preprocess?text=dabur honey kitna hai">dabur honey kitna hai</a></li>
                            </ul>
                        </div>
                    </div>
                    
                    <!-- Personal Care (pieces) -->
                    <div class="example-group">
                        <h3>🧴 Personal Care (pieces)</h3>
                        <div class="product-category">
                            <strong>Soap:</strong>
                            <ul>
                                <li><a href="/preprocess?text=3 soap beche">3 soap beche</a></li>
                                <li><a href="/preprocess?text=10 soap pieces aa gaye">10 soap pieces aa gaye</a></li>
                                <li><a href="/preprocess?text=soap ka stock bataye">soap ka stock bataye</a></li>
                            </ul>
                        </div>
                    </div>
                    
                </div>
                
                <!-- Mixed Examples -->
                <div class="example-group" style="grid-column: 1 / -1; margin-top: 20px;">
                    <h3>🔀 Mixed & Advanced Examples</h3>
                    <div class="examples-grid">
                        <div class="product-category">
                            <strong>Multiple Items:</strong>
                            <ul>
                                <li><a href="/preprocess?text=2 kg aata aur 1 liter milk beche">2 kg aata aur 1 liter milk beche</a></li>
                                <li><a href="/preprocess?text=5 parle g aur 3 lays bik gaye">5 parle g aur 3 lays bik gaye</a></li>
                            </ul>
                        </div>
                        <div class="product-category">
                            <strong>Hindi Phrases:</strong>
                            <ul>
                                <li><a href="/preprocess?text=do kilo aata beche">do kilo aata beche</a></li>
                                <li><a href="/preprocess?text=paanch liter doodh aa gaya">paanch liter doodh aa gaya</a></li>
                                <li><a href="/preprocess?text=teen packet parle g bik gaye">teen packet parle g bik gaye</a></li>
                            </ul>
                        </div>
                        <div class="product-category">
                            <strong>English Phrases:</strong>
                            <ul>
                                <li><a href="/preprocess?text=sold 2 kg flour">sold 2 kg flour</a></li>
                                <li><a href="/preprocess?text=restock 5 packets of lays">restock 5 packets of lays</a></li>
                                <li><a href="/preprocess?text=check stock of rice">check stock of rice</a></li>
                            </ul>
                        </div>
                    </div>
                </div>
            </div>

            <div style="background: #e8f5e8; padding: 15px; border-radius: 5px; margin: 15px 0;">
                <h3>📋 Supported Units & Products</h3>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px;">
                    <div>
                        <h4>⚖️ Weight Units</h4>
                        <ul>
                            <li>kg, kilo, kilogram</li>
                            <li>g, grams, gm</li>
                        </ul>
                    </div>
                    <div>
                        <h4>💧 Volume Units</h4>
                        <ul>
                            <li>liters, liter, l</li>
                            <li>ml, milliliter</li>
                        </ul>
                    </div>
                    <div>
                        <h4>📦 Discrete Units</h4>
                        <ul>
                            <li>packets, packet, pkt</li>
                            <li>bottles, bottle</li>
                            <li>pieces, piece, pcs</li>
                        </ul>
                    </div>
                </div>
                
                <h4>🏪 All Products</h4>
                <p><strong>Weight-based:</strong> Aata (flour), Chawal (rice), Dal (lentils), Sugar, Tea</p>
                <p><strong>Volume-based:</strong> Milk, Oil</p>
                <p><strong>Packaged:</strong> Parle-G, Lays, Dabur Honey, Tata Salt, Coke</p>
                <p><strong>Personal Care:</strong> Soap</p>
            </div>

            <h3>🔗 Endpoints</h3>
            <ul>
                <li><strong><a href="/preprocess?text=2 kg aata beche">/preprocess?text=your_text</a></strong> - Test voice commands</li>
                <li><strong><a href="/inventory">/inventory</a></strong> - Get inventory data (JSON API)</li>
                <li><strong><a href="/reset">/reset</a></strong> - Reset inventory to default values</li>
                <li><strong><a href="/test_audio?file=test.wav">/test_audio?file=audio.wav</a></strong> - Test audio files</li>
            </ul>
        </div>
    </body>
    </html>
    """

if __name__ == '__main__':
    print("\n🎯 Voice Inventory Management System with Measurement Units")
    print("📍 Now supports: kg, g, liters, ml, packets, bottles, pieces")
    print("📍 Access: http://localhost:5000")
    print("\n🌟 Try these measurement commands:")
    print("   • http://localhost:5000/preprocess?text=2 kg aata beche")
    print("   • http://localhost:5000/preprocess?text=5 liters milk aa gaya")
    print("   • http://localhost:5000/preprocess?text=500 g sugar beche")
    print("\nType Ctrl+C to stop the server\n")
    
    app.run(host='0.0.0.0', port=5000, debug=True)