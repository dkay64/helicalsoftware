import cv2
import numpy as np
import os
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
RTSP_URL = "rtsp://192.168.0.102:8554/cam?tcp_timeout=5000000"
# In the VideoCapture line:
cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
# --- CONFIGURATION ---
# Use the NEW IP address of your Jetson here
JETSON_IP = "192.168.0.102" 
RTSP_URL = f"rtsp://{JETSON_IP}:8554/cam"

# The center of your 720x1280 vertical feed
CENTER_X = 360 

def run_calibration():
    # cv2.CAP_FFMPEG tells OpenCV to use the high-speed decoder
    cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
    
    # Set internal buffer to 1 to minimize lag
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    if not cap.isOpened():
        print(f"Error: Could not connect to Jetson at {RTSP_URL}")
        return

    print("Connected to Jetson. Press 'q' to quit.")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Dropped frame or connection lost.")
            break
        cv2.line(frame, (CENTER_X, 0), (CENTER_X, 1280), (255,0, 0), 2)
        cv2.line(frame, (CENTER_X-5, 0), (CENTER_X-5, 1280), (200,200,200),1)
        cv2.line(frame, (CENTER_X+5, 0), (CENTER_X+5, 1280), (200, 200, 200), 1)
        cv2.putText(frame, "MAC-SIDE PROCESSING", (30, 50), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        # Show the result in a native window
        cv2.imshow("Jetson Calibration Feed", frame)

        # Press 'q' to exit
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    run_calibration()