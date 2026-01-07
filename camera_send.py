def camera_send_loop(conn):
    """
    Picamera2 기반 카메라 프레임을 JPEG으로 인코딩하여
    TCP로 서버에 지속 전송
    """
    from picamera2 import Picamera2
    import cv2
    import time

    print("[PI] starting Picamera2...")

    picam2 = Picamera2()
    config = picam2.create_video_configuration(
        main={
            "size": (640, 480),
            "format": "RGB888"
        }
    )
    picam2.configure(config)
    picam2.start()

    print("[PI] Picamera2 started")

    frame_interval = 1.0 / float(SEND_FPS)
    last_time = time.time()

    encode_param = [
        int(cv2.IMWRITE_JPEG_QUALITY),
        int(JPEG_QUALITY)
    ]

    try:
        while True:
            # 1️⃣ 프레임 캡처 (RGB)
            frame = picam2.capture_array()

            # 2️⃣ OpenCV용 BGR 변환
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

            # 3️⃣ JPEG 인코딩
            ok, jpg = cv2.imencode(".jpg", frame, encode_param)
            if not ok:
                continue

            # 4️⃣ 서버로 전송
            send_msg(conn, TYPE_IMAGE, jpg.tobytes())

            # 5️⃣ FPS 제어
            now = time.time()
            dt = now - last_time
            if dt < frame_interval:
                time.sleep(frame_interval - dt)
            last_time = time.time()

    except Exception as e:
        print("[PI] camera_send_loop error:", e)

    finally:
        picam2.stop()
        print("[PI] Picamera2 stopped")
