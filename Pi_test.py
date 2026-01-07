import socket, struct, threading, time, json
import cv2

# =========================
# 설정
# =========================
SERVER_IP = "192.168.0.25"   # ✅ PC(서버) IP로 바꿔줘
SERVER_PORT = 6000

TYPE_SENSOR = 1
TYPE_IMAGE  = 2
TYPE_CMD    = 3

JPEG_QUALITY = 70
SEND_FPS = 10                # 카메라 전송 FPS (10~15 권장)
SENSOR_INTERVAL = 1.0        # 센서 전송 주기(초)

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
    header = recvall(conn, 5)  # 1B type + 4B length
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

                # 예: {"cmd":"ALERT","payload":{"type":"person","message":"사람이 앞에 있습니다"}}
                obj = json.loads(text)
                if obj.get("cmd") == "ALERT":
                    p = obj.get("payload", {})
                    msg = p.get("message", "경고")
                    # 여기서 TTS/부저/스피커 출력 연결하면 됨
                    print("[PI][ALERT]", msg)

            except Exception as e:
                print("[PI] CMD parse error:", e)

# =========================
# 센서 전송 루프 (예시)
# =========================
def sensor_send_loop(conn):
    while True:
        try:
            # ✅ 너 프로젝트에 맞게 초음파/기타 센서값 넣으면 됨
            data = {
                "ultrasonic_cm": None,
                "ts": time.time()
            }
            msg = json.dumps(data, ensure_ascii=False).encode("utf-8")
            send_msg(conn, TYPE_SENSOR, msg)
        except Exception as e:
            print("[PI] sensor send error:", e)
            break
        time.sleep(SENSOR_INTERVAL)

# =========================
# 카메라 전송 루프
# =========================
def camera_send_loop(conn):
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[PI] camera open failed")
        return

    frame_interval = 1.0 / float(SEND_FPS)
    last = time.time()

    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), int(JPEG_QUALITY)]

    while True:
        ok, frame = cap.read()
        if not ok:
            print("[PI] camera read failed")
            break

        # 필요하면 크기 줄여서 속도 올리기
        # frame = cv2.resize(frame, (640, 480))

        ok, jpg = cv2.imencode(".jpg", frame, encode_param)
        if not ok:
            continue

        try:
            send_msg(conn, TYPE_IMAGE, jpg.tobytes())
        except Exception as e:
            print("[PI] image send error:", e)
            break

        # FPS 제어
        now = time.time()
        dt = now - last
        if dt < frame_interval:
            time.sleep(frame_interval - dt)
        last = time.time()

    cap.release()

# =========================
# main
# =========================
def main():
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

            # 연결 유지 (cmd thread가 끊기면 재접속)
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

if __name__ == "__main__":
    main()
