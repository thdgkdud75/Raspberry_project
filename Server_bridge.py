import eventlet
eventlet.monkey_patch()  # ✅ 웹소켓/이벤트루프 안정화(중요)

import socket, struct, threading, json, base64, time
from flask import Flask, send_from_directory
from flask_socketio import SocketIO

# =========================
# 설정
# =========================
TCP_HOST = "0.0.0.0"
TCP_PORT = 6000

WEB_HOST = "0.0.0.0"
WEB_PORT = 8000

TYPE_SENSOR = 1
TYPE_IMAGE  = 2
TYPE_CMD    = 3

app = Flask(__name__, static_folder=".")
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="eventlet",
    max_http_buffer_size=50 * 1024 * 1024,  # ✅ 큰 base64 프레임 버퍼(중요)
)

pi_conn = None
pi_lock = threading.Lock()
last_frame_ts = 0.0
last_sensor_ts = 0.0

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

def tcp_pi_thread():
    global pi_conn, last_frame_ts, last_sensor_ts

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((TCP_HOST, TCP_PORT))
    s.listen(1)
    print(f"[TCP] waiting Pi on {TCP_PORT}...")

    conn, addr = s.accept()
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print("[TCP] Pi connected:", addr)

    with pi_lock:
        pi_conn = conn

    try:
        while True:
            mtype, payload = recv_msg(conn)
            if mtype is None:
                print("[TCP] Pi disconnected")
                break

            if mtype == TYPE_SENSOR:
                last_sensor_ts = time.time()
                msg = payload.decode("utf-8", errors="replace")
                print("[TCP] SENSOR IN:", msg[:120])
                socketio.emit("sensor", msg)

            elif mtype == TYPE_IMAGE:
                last_frame_ts = time.time()
                print("[TCP] IMAGE IN bytes =", len(payload))
                b64 = base64.b64encode(payload).decode("ascii")
                socketio.emit("frame", b64)

            elif mtype == TYPE_CMD:
                # Pi -> Server로 CMD 올 수도 있음(로그용)
                print("[TCP] CMD FROM PI:", payload[:200])

    except Exception as e:
        print("[TCP] error:", e)
    finally:
        with pi_lock:
            pi_conn = None
        try:
            conn.close()
        except:
            pass
        s.close()

@app.route("/")
def root():
    return send_from_directory(".", "index.html")

@app.route("/health")
def health():
    return {
        "pi_connected": pi_conn is not None,
        "last_frame_age_sec": None if last_frame_ts == 0 else round(time.time() - last_frame_ts, 2),
        "last_sensor_age_sec": None if last_sensor_ts == 0 else round(time.time() - last_sensor_ts, 2),
    }

@socketio.on("connect")
def on_connect():
    print("[WEB] browser connected")

@socketio.on("disconnect")
def on_disconnect():
    print("[WEB] browser disconnected")

@socketio.on("alert")
def on_alert(data):
    """
    브라우저(ml5)에서 탐지 -> 서버 -> Pi로 전달
    data 예: { type:'person', confidence:0.78, message:'사람이 앞에 있습니다' }
    """
    cmd = json.dumps({"cmd": "ALERT", "payload": data}, ensure_ascii=False).encode("utf-8")
    with pi_lock:
        if not pi_conn:
            print("[CMD] Pi not connected, drop alert")
            return
        try:
            send_msg(pi_conn, TYPE_CMD, cmd)
            print("[CMD] ALERT -> Pi", data)
        except Exception as e:
            print("[CMD] send to Pi failed:", e)

if __name__ == "__main__":
    threading.Thread(target=tcp_pi_thread, daemon=True).start()
    print(f"[WEB] open http://localhost:{WEB_PORT}")
    print(f"[WEB] health http://localhost:{WEB_PORT}/health")
    socketio.run(app, host=WEB_HOST, port=WEB_PORT)
