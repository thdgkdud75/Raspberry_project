import socket, struct, threading, time, json
import cv2
import RPi.GPIO as GPIO  # ✅ GPIO 라이브러리 추가

# =========================
# 설정
# =========================
SERVER_IP = "192.168.0.26"   # 서버 PC IP
SERVER_PORT = 6000

TYPE_SENSOR = 1
TYPE_IMAGE  = 2
TYPE_CMD    = 3

JPEG_QUALITY = 70
SEND_FPS = 10                # 카메라 전송 FPS
SENSOR_INTERVAL = 0.5        # ✅ 센서 측정 주기 (초) - 반응 속도를 위해 0.5초로 단축 추천

# ✅ 초음파 센서 핀 설정 (BCM 모드 기준)
TRIG_PIN = 18
ECHO_PIN = 16

# =========================
# GPIO 초기화 함수
# =========================
def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(TRIG_PIN, GPIO.OUT)
    GPIO.setup(ECHO_PIN, GPIO.IN)
    
    # 초기에 TRIG를 Low로 설정
    GPIO.output(TRIG_PIN, False)
    time.sleep(1) # 센서 안정화 대기
    print("[PI] GPIO & Sensor Ready")

# =========================
# 초음파 거리 측정 함수
# =========================
def get_distance():
    try:
        # 1. TRIG 핀에 10us 펄스 발사
        GPIO.output(TRIG_PIN, True)
        time.sleep(0.00001)
        GPIO.output(TRIG_PIN, False)

        pulse_start = time.time()
        pulse_end = time.time()
        
        # 무한 대기 방지를 위한 타임아웃 설정 (약 0.1초)
        timeout = pulse_start + 0.1

        # 2. ECHO 핀이 High가 될 때까지 대기 (시작 시간)
        while GPIO.input(ECHO_PIN) == 0:
            pulse_start = time.time()
            if pulse_start > timeout:
                return None # 타임아웃

        # 3. ECHO 핀이 Low가 될 때까지 대기 (종료 시간)
        while GPIO.input(ECHO_PIN) == 1:
            pulse_end = time.time()
            if pulse_end > timeout:
                return None # 타임아웃

        # 4. 거리 계산
        # 거리 = 시간 * 속도(34300cm/s) / 2 (왕복이므로)
        pulse_duration = pulse_end - pulse_start
        distance = pulse_duration * 17150
        distance = round(distance, 2)
        
        # 노이즈 필터링 (너무 먼 거리는 무시 - 예: 4m 이상)
        if distance > 400:
            return None
            
        return distance

    except Exception as e:
        print("[PI] Distance calc error:", e)
        return None

# =========================
# TCP 프로토콜 함수
# =========================
def recvall(conn, n):
    data = b""
    while len(data) < n:
        chunk = conn.recv(n - len(data))
        if not chunk:
            return None
        data += chunk
    return data

def recv_msg(conn):
    header = recvall(conn, 5)
    if header is None:
        return None, None
    mtype, length = struct.unpack("!BI", header)
    payload = recvall(conn, length)
    if payload is None:
        return None, None
    return mtype, payload

def send_msg(conn, mtype, payload: bytes):
    conn.sendall(struct.pack("!BI", mtype, len(payload)) + payload)

# =========================
# CMD 수신 루프 (서버 -> Pi)
# =========================
def cmd_recv_loop(conn):
    while True:
        mtype, payload = recv_msg(conn)
        if mtype is None:
            print("[PI] server disconnected (recv)")
            break

        if mtype == TYPE_CMD:
            try:
                text = payload.decode("utf-8", errors="replace")
                print("[PI] CMD IN:", text)

                obj = json.loads(text)
                if obj.get("cmd") == "ALERT":
                    p = obj.get("payload", {})
                    msg = p.get("message", "경고")
                    print("[PI][ALERT]", msg)
                    # 💡 여기에 부저나 진동 모터 코드를 추가하면 좋습니다.

            except Exception as e:
                print("[PI] CMD parse error:", e)

# =========================
# 센서 전송 루프 (초음파 적용)
# =========================
def sensor_send_loop(conn):
    while True:
        try:
            # ✅ 실제 거리 측정
            dist = get_distance()
            
            # (디버깅용) 터미널에 출력
            # if dist: print(f"Distance: {dist}cm")

            data = {
                "ultrasonic_cm": dist,  # 측정값 넣기
                "ts": time.time()
            }
            msg = json.dumps(data, ensure_ascii=False).encode("utf-8")
            send_msg(conn, TYPE_SENSOR, msg)
        
        except Exception as e:
            print("[PI] sensor send error:", e)
            break
        
        time.sleep(SENSOR_INTERVAL)

# =========================
# 카메라 전송 루프 (GStreamer)
# =========================
def camera_send_loop(conn):
    cap = None
    print("[PI] 📸 GStreamer 파이프라인으로 카메라 연결 시도 중...")

    gst_str = (
        "libcamerasrc ! "
        "video/x-raw, width=640, height=480, framerate=15/1 ! "
        "videoconvert ! "
        "appsink"
    )

    cap = cv2.VideoCapture(gst_str, cv2.CAP_GSTREAMER)

    if cap.isOpened():
        print("[PI] ✅ GStreamer 카메라 연결 성공!")
    else:
        print("[PI] ❌ 카메라 연결 실패 (GStreamer 모듈 확인 필요)")
        return

    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), int(JPEG_QUALITY)]
   
    while True:
        ret, frame = cap.read()
        if not ret:
            print("[PI] 프레임 읽기 실패 (잠시 대기)")
            time.sleep(1)
            continue
           
        try:
            _, jpg = cv2.imencode(".jpg", frame, encode_param)
            send_msg(conn, TYPE_IMAGE, jpg.tobytes())
        except Exception as e:
            print("[PI] 전송 중 에러:", e)
            break
           
        time.sleep(0.01)

    cap.release()

# =========================
# main
# =========================
def main():
    # ✅ 프로그램 시작 시 GPIO 설정
    setup_gpio()

    while True:
        try:
            print(f"[PI] connecting to {SERVER_IP}:{SERVER_PORT} ...")
            conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            conn.connect((SERVER_IP, SERVER_PORT))
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            print("[PI] connected!")

            t_cmd = threading.Thread(target=cmd_recv_loop, args=(conn,), daemon=True)
            t_sen = threading.Thread(target=sensor_send_loop, args=(conn,), daemon=True)
            t_cam = threading.Thread(target=camera_send_loop, args=(conn,), daemon=True)

            t_cmd.start()
            t_sen.start()
            t_cam.start()

            while t_cmd.is_alive() and t_cam.is_alive():
                time.sleep(1)

        except Exception as e:
            print("[PI] connect/run error:", e)

        try:
            conn.close()
        except:
            pass

        print("[PI] retry in 2 sec...")
        time.sleep(2)
    
    # 프로그램 종료 시 GPIO 정리 (무한루프라 도달하진 않지만 관례상)
    GPIO.cleanup()

if __name__ == "__main__":
    main()