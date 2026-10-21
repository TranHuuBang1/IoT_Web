import os
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import paho.mqtt.client as mqtt
import ssl
import time
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

AES_KEY = b"1234567890123456"

# Biến bộ nhớ tạm lưu dữ liệu cảm biến mới nhất
sensor_data = {
    "temperature": "--",
    "humidity": "--",
    "light": "--"
}

# ==========================================
# HÀM MÃ HÓA & GIẢI MÃ AES-128
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
# MQTT BACKGROUND CLIENT CHO RENDER (ĐỌC NGẦM DỮ LIỆU)
# ==========================================
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("-> MQTT Background đã kết nối thành công với HiveMQ!")
        client.subscribe("tro/room1/temperature")
        client.subscribe("tro/room1/humidity")
        client.subscribe("tro/room1/light")
    else:
        print(f"-> MQTT Kết nối thất bại, mã lỗi: {rc}")

def on_message(client, userdata, msg):
    global sensor_data
    try:
        payload_decrypted = decrypt_aes(msg.payload.decode('utf-8'))
        topic = msg.topic
        if "temperature" in topic:
            sensor_data["temperature"] = payload_decrypted
        elif "humidity" in topic:
            sensor_data["humidity"] = payload_decrypted
        elif "light" in topic:
            sensor_data["light"] = payload_decrypted
        print(f"Cập nhật cảm biến từ Broker: {sensor_data}")
    except Exception as e:
        print(f"Lỗi giải mã: {e}")

# Khởi tạo client chạy ngầm trong Flask
mqtt_bg = mqtt.Client(client_id=f"render_bg_listener_{os.getpid()}")
mqtt_bg.username_pw_set(MQTT_USER, MQTT_PASSWORD)
mqtt_bg.tls_set(cert_reqs=ssl.CERT_NONE)
mqtt_bg.tls_insecure_set(True)
mqtt_bg.on_connect = on_connect
mqtt_bg.on_message = on_message

try:
    mqtt_bg.connect(MQTT_SERVER, MQTT_PORT, 60)
    mqtt_bg.loop_start()
except Exception as e:
    print(f"Lỗi khởi chạy MQTT Background: {e}")

# ==========================================
# HÀM GỬI LỆNH MQTT (ĐIỀU KHIỂN BẬT/TẮT)
# ==========================================
def send_mqtt_command(topic, message):
    client = None
    try:
        client_id = f"flask_cmd_{os.getpid()}_{int(time.time())}"
        client = mqtt.Client(client_id=client_id)
        client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
        client.tls_set(cert_reqs=ssl.CERT_NONE)
        client.tls_insecure_set(True)
        
        client.connect(MQTT_SERVER, MQTT_PORT, 60)
        client.loop_start()
        
        encrypted_cmd = encrypt_aes(message)
        result = client.publish(topic, encrypted_cmd)
        result.wait_for_publish(timeout=3)
        
        time.sleep(0.3)
        client.loop_stop()
        client.disconnect()
    except Exception as e:
        print(f"Lỗi gửi MQTT: {e}")
        if client:
            try:
                client.loop_stop()
                client.disconnect()
            except:
                pass

# ==========================================
# ROUTE WEB DASHBOARD
# ==========================================
@app.route("/")
def home():
    return render_template("index.html")

# ==========================================
# API AI CHATBOT
# ==========================================
@app.route('/api/chat', methods=['POST'])
def chat_ai():
    data = request.json
    user_message = data.get('message', '').lower().strip()
    
    response_text = "Xin lỗi, tôi chưa hiểu ý bạn. Bạn có thể hỏi thời tiết/nhiệt độ hoặc ra lệnh bật/tắt đèn nhé."
    
    # 1. Hỏi thời tiết / nhiệt độ / độ ẩm -> Đọc trực tiếp từ bộ nhớ tạm
    if any(kw in user_message for kw in ["thời tiết", "nhiệt độ", "độ ẩm", "phòng trọ", "bao nhiêu độ", "thế nào", "ra sao"]):
        temp = sensor_data["temperature"]
        hum = sensor_data["humidity"]
        light = sensor_data["light"]

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

    return jsonify({"reply": response_text})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)