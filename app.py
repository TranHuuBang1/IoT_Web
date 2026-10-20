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

AES_KEY = b"1234567890123456"

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
# HÀM GỬI LỆNH MQTT AN TOÀN TRÊN RENDER
# ==========================================
def send_mqtt_command(topic, message):
    try:
        client = mqtt.Client()
        client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
        client.tls_set()
        client.connect(MQTT_SERVER, MQTT_PORT, 60)
        encrypted_cmd = encrypt_aes(message)
        client.publish(topic, encrypted_cmd)
        client.disconnect()
    except Exception as e:
        print(f"Lỗi gửi MQTT: {e}")

# ==========================================
# ROUTE WEB DASHBOARD
# ==========================================
@app.route("/")
def home():
    return render_template("index.html")

# ==========================================
# API AI CHATBOT (LẤY DỮ LIỆU TRỰC TIẾP TỪ MQTT)
# ==========================================
@app.route('/api/chat', methods=['POST'])
def chat_ai():
    data = request.json
    user_message = data.get('message', '').lower().strip()
    
    response_text = "Xin lỗi, tôi chưa hiểu ý bạn. Bạn có thể hỏi thời tiết/nhiệt độ hoặc ra lệnh bật/tắt đèn nhé."
    
    # 1. Hỏi về thời tiết / nhiệt độ / độ ẩm -> Đọc trực tiếp từ HiveMQ Cloud khi người dùng hỏi
    if any(kw in user_message for kw in ["thời tiết", "nhiệt độ", "độ ẩm", "phòng trọ", "bao nhiêu độ", "thế nào", "ra sao"]):
        temp, hum, light = "--", "--", "--"
        try:
            # Kết nối nhanh tới MQTT Broker để lấy giá trị mới nhất
            import paho.mqtt.subscribe as subscribe
            # Đọc nhanh các topic cảm biến từ Broker
            msg_temp = subscribe.simple("tro/room1/temperature", hostname=MQTT_SERVER, port=MQTT_PORT, auth={'username':MQTT_USER, 'password':MQTT_PASSWORD}, tls={'ca_certs':None}, timeout=2)
            msg_hum = subscribe.simple("tro/room1/humidity", hostname=MQTT_SERVER, port=MQTT_PORT, auth={'username':MQTT_USER, 'password':MQTT_PASSWORD}, tls={'ca_certs':None}, timeout=2)
            msg_light = subscribe.simple("tro/room1/light", hostname=MQTT_SERVER, port=MQTT_PORT, auth={'username':MQTT_USER, 'password':MQTT_PASSWORD}, tls={'ca_certs':None}, timeout=2)
            
            temp = decrypt_aes(msg_temp.payload.decode('utf-8'))
            hum = decrypt_aes(msg_hum.payload.decode('utf-8'))
            light = decrypt_aes(msg_light.payload.decode('utf-8'))
        except Exception as e:
            print(f"Lỗi đọc MQTT: {e}")

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