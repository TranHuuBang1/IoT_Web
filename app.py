import os
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import paho.mqtt.client as mqtt
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

app = Flask(__name__)
CORS(app)

# ==========================================
# CẤU HÌNH MQTT & BẢO MẬT AES-128
# ==========================================
MQTT_SERVER = "9362e9a942044f75a1aaa3b24f00a524.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_USER = "esp32"
MQTT_PASSWORD = "tranhuubang"

# Khóa bí mật AES (Phải trùng khớp 16 bytes với ESP32 và Web)
AES_KEY = b"1234567890123456"

# Biến lưu trữ cảm biến mới nhất trên RAM Server
latest_data = {
    "temperature": "--",
    "humidity": "--",
    "light": "--",
    "led_state": "OFF",
    "buzzer_state": "OFF",
    "mode": "MANUAL"
}

# ==========================================
# HÀM MÃ HÓA & GIẢI MÃ AES-128 (PKCS7 Padding)
# ==========================================
def decrypt_aes(cipher_hex):
    try:
        cipher_bytes = bytes.fromhex(cipher_hex)
        cipher = Cipher(algorithms.AES(AES_KEY), modes.ECB(), backend=default_backend())
        decryptor = cipher.decryptor()
        padded_data = decryptor.update(cipher_bytes) + decryptor.finalize()
        
        padding_length = padded_data[-1]
        return padded_data[:-padding_length].decode('utf-8')
    except Exception as e:
        print(f"Lỗi giải mã: {e}")
        return ""

def encrypt_aes(plain_text):
    cipher = Cipher(algorithms.AES(AES_KEY), modes.ECB(), backend=default_backend())
    encryptor = cipher.encryptor()
    
    text_bytes = plain_text.encode('utf-8')
    padding_length = 16 - (len(text_bytes) % 16)
    padded_data = text_bytes + bytes([padding_length] * padding_length)
    
    encrypted_bytes = encryptor.update(padded_data) + encryptor.finalize()
    return encrypted_bytes.hex().upper()

# ==========================================
# HÀM GỬI LỆNH MQTT AN TOÀN TRÊN CLOUD/RENDER
# ==========================================
def send_mqtt_command(topic, message):
    try:
        client = mqtt.Client()
        client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
        client.tls_set()  # Kết nối bảo mật TLS cổng 8883
        client.connect(MQTT_SERVER, MQTT_PORT, 60)
        
        # Mã hóa AES trước khi gửi xuống phần cứng
        encrypted_cmd = encrypt_aes(message)
        client.publish(topic, encrypted_cmd)
        client.disconnect()
        print(f"✅ Đã gửi MQTT thành công tới {topic}: {encrypted_cmd}")
    except Exception as e:
        print(f"❌ Lỗi gửi MQTT: {e}")

# ==========================================
# MQTT CLIENT BACKGROUND LISTENER (LẮNG NGHE CẢM BIẾN)
# ==========================================
def on_connect(client, userdata, flags, rc):
    print("✅ Đã kết nối MQTT Broker thành công để lắng nghe!")
    client.subscribe("tro/room1/#")

def on_message(client, userdata, msg):
    global latest_data
    topic = msg.topic
    payload = msg.payload.decode('utf-8')
    
    # Giải mã dữ liệu nhận từ ESP32
    decrypted_msg = decrypt_aes(payload)
    
    if "temperature" in topic:
        latest_data["temperature"] = decrypted_msg
    elif "humidity" in topic:
        latest_data["humidity"] = decrypted_msg
    elif "light" in topic and "state" not in topic:
        latest_data["light"] = decrypted_msg
    elif "light/state" in topic:
        latest_data["led_state"] = decrypted_msg
    elif "buzzer/state" in topic:
        latest_data["buzzer_state"] = decrypted_msg
    elif "mode/state" in topic:
        latest_data["mode"] = decrypted_msg

# Khởi chạy luồng ngầm lắng nghe dữ liệu cảm biến
try:
    background_client = mqtt.Client()
    background_client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    background_client.tls_set()
    background_client.on_connect = on_connect
    background_client.on_message = on_message
    background_client.connect(MQTT_SERVER, MQTT_PORT, 60)
    background_client.loop_start()
except Exception as e:
    print(f"Không thể khởi động background MQTT client: {e}")

# ==========================================
# ROUTE WEB DASHBOARD
# ==========================================
@app.route("/")
def home():
    return render_template("index.html")

# ==========================================
# API AI CHATBOT (XỬ LÝ NGÔN NGỮ TỰ NHIÊN)
# ==========================================
@app.route('/api/chat', methods=['POST'])
def chat_ai():
    data = request.json
    user_message = data.get('message', '').lower().strip()
    
    response_text = "Xin lỗi, tôi chưa hiểu ý bạn. Bạn có thể hỏi thời tiết/nhiệt độ hoặc ra lệnh bật/tắt đèn nhé."
    
    # 1. Hỏi về thời tiết / nhiệt độ / độ ẩm
    if any(kw in user_message for kw in ["thời tiết", "nhiệt độ", "độ ẩm", "phòng trọ", "bao nhiêu độ", "thế nào", "ra sao"]):
        temp = latest_data["temperature"]
        hum = latest_data["humidity"]
        light = latest_data["light"]
        
        analysis = ""
        try:
            t_val = float(temp)
            if t_val > 32:
                analysis = "\n🔥 Nhiệt độ khá cao và oi bức, bạn nên bật quạt hoặc máy lạnh cho thoải mái nhé."
            elif t_val < 20:
                analysis = "\n❄️ Trời đang khá lạnh, hãy giữ ấm cơ thể nhé."
            else:
                analysis = "\n👍 Thời tiết trong phòng hiện tại rất dễ chịu."
        except:
            analysis = ""
            
        response_text = f"📊 Thông số phòng hiện tại:\n- Nhiệt độ: {temp} °C\n- Độ ẩm: {hum} %\n- Ánh sáng (ADC): {light} adc{analysis}"

    # 2. Ra lệnh BẬT ĐÈN
    elif "bật" in user_message and ("đèn" in user_message or "sáng" in user_message):
        send_mqtt_command("tro/room1/light/control", "ON")
        response_text = "💡 Đã nhận lệnh! Tôi đã bật đèn phòng cho bạn rồi nhé."

    # 3. Ra lệnh TẮT ĐÈN
    elif "tắt" in user_message and ("đèn" in user_message or "tối" in user_message):
        send_mqtt_command("tro/room1/light/control", "OFF")
        response_text = "🌙 Đã nhận lệnh! Tôi đã tắt đèn phòng giúp bạn."

    # 4. Điều khiển CÒI BÁO (Buzzer)
    elif "bật" in user_message and ("còi" in user_message or "báo động" in user_message):
        send_mqtt_command("tro/room1/buzzer/control", "ON")
        response_text = "🚨 Đã kích hoạt còi báo động!"
        
    elif "tắt" in user_message and ("còi" in user_message or "báo động" in user_message):
        send_mqtt_command("tro/room1/buzzer/control", "OFF")
        response_text = "🔕 Đã tắt còi báo động."

    # 5. Hỏi trạng thái chế độ AUTO/MANUAL
    elif "chế độ" in user_message or "trạng thái" in user_message:
        response_text = f"⚙️ Trạng thái thiết bị hiện tại:\n- Chế độ: {latest_data['mode']}\n- Đèn LED: {latest_data['led_state']}\n- Còi: {latest_data['buzzer_state']}"

    return jsonify({"reply": response_text})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)