import socket, struct, time, json, threading, subprocess
import cv2
from picamera2 import Picamera2

# =========================
# 서버 설정
# =========================
SERVER_IP = "192.168.0.25"  # ★ PC IP
SERVER_PORT = 6000

# ✅ 빠르게 뜨게 하는 기본값
FPS = 12
JPEG_QUALITY = 50

TYPE_SENSOR = 1
TYPE_IMAGE  = 2
TYPE_CMD    = 3

# =========================
# 초음파(HC-SR04) GPIO 설정 (BCM)
# =========================
TRIG = 23
ECHO = 24

def setup_ultrasonic():
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(TRIG, GPIO.OUT)
    GPIO.setup(ECHO, GPIO.IN)
    GPIO.output(TRIG, False)
    time.sleep(0.1)
    return GPIO

def read_distance_cm(GPIO):
    GPIO.output(TRIG, False)
    time.sleep(0.0002)

    GPIO.output(TRIG, True)
    time.sleep(0.00001)
    GPIO.output(TRIG, False)

    timeout = 0.03
    t0 = time.time()

    while GPIO.input(ECHO) == 0:
        if time.time() - t0 > timeout:
            return 999.0
    start = time.time()

    while GPIO.input(ECHO) == 1:
        if time.time() - start > timeout:
            return 999.0
    end = time.time()

    return float((end - start) * 34300 / 2)

def send_msg(sock, mtype: int, payload: bytes):
    sock.sendall(struct.pack("!BI", mtype, len(payload)) + payload)

def recvall(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            return None
        data += chunk
    return data

def recv_msg(sock):
    header = recvall(sock, 5)
    if header is None:
        return None, None
    mtype, length = struct.unpack("!BI", header)
    payload = recvall(sock, length)
    if payload is None:
        return None, None
    return mtype, payload

def play_alert():
    subprocess.Popen(["aplay", "/home/pi/alert.wav"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def cmd_listener(sock):
    while True:
        mtype, payload = recv_msg(sock)
        if mtype is None:
            print("[Pi] server disconnected (cmd_listener)")
            break
        if mtype == TYPE_CMD:
            try:
                cmd = json.loads(payload.decode("utf-8"))
                if cmd.get("cmd") == "ALERT":
                    print("[Pi] ALERT received -> play sound")
                    play_alert()
            except Exception as e:
                print("[Pi] cmd parse error:", e)

def main():
    GPIO = setup_ultrasonic()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((SERVER_IP, SERVER_PORT))
    print("[Pi] connected to server")

    threading.Thread(target=cmd_listener, args=(sock,), daemon=True).start()

    picam2 = Picamera2()

    # ✅ 기본 640x480 (느리면 320x240으로 바꿔서 테스트)
    cfg = picam2.create_video_configuration(main={"size": (640, 480), "format": "RGB888"})
    # cfg = picam2.create_video_configuration(main={"size": (320, 240), "format": "RGB888"})  # ← 더 빠름

    picam2.configure(cfg)
    picam2.start()
    time.sleep(0.5)

    interval = 1.0 / FPS
    frame_count = 0

    try:
        while True:
            t0 = time.time()

            dist = read_distance_cm(GPIO)
            sensors = {"ultrasonic_cm": dist, "ts": time.time()}
            send_msg(sock, TYPE_SENSOR, json.dumps(sensors).encode("utf-8"))

            frame = picam2.capture_array()  # RGB
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            ok, enc = cv2.imencode(".jpg", frame_bgr,
                                   [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
            if ok:
                jpg = enc.tobytes()
                send_msg(sock, TYPE_IMAGE, jpg)
            else:
                jpg = b""

            frame_count += 1
            if frame_count % 12 == 0:
                print(f"[Pi] sent dist={dist:.1f}cm, jpg_bytes={len(jpg)}")

            dt = time.time() - t0
            if interval - dt > 0:
                time.sleep(interval - dt)

    except KeyboardInterrupt:
        print("[Pi] stopped by user")
    except Exception as e:
        print("[Pi] error:", e)
    finally:
        try:
            picam2.stop()
        except:
            pass
        try:
            sock.close()
        except:
            pass
        try:
            GPIO.cleanup()
        except:
            pass
        print("[Pi] cleanup done")

if __name__ == "__main__":
    main()
