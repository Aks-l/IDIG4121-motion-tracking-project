import cv2
import numpy as np

K = np.array([
        [800, 0, 960],
        [0, 800, 540],
        [0, 0, 1]
    ], dtype=np.float64)

D = np.array([-0.1, 0.01, 0.0, 0.0], dtype=np.float64)

def capture_streaming() -> None:
    cap = cv2.VideoCapture(1)
    bg = cv2.imread("snapshot.jpg", cv2.IMREAD_GRAYSCALE)

    if not cap.isOpened():
        print("Error: Could not open video stream.")
        return

    print("Streaming started. Press 'q' or close the window to exit.")

    window_name = "Live Video Stream"

    try:
        while True:
            ret, frame = cap.read()

            if not ret:
                print("Error: Can't receive frame. Exiting...")
                break
            # Convert live frame to grayscale

            h, w = frame.shape[:2]

            #new_K = cv2.fisheye.estimateNewCameraMatrixForUndistortRectify(K, D, (w, h), np.eye(3), balance=0.0)

            #undistorted = cv2.fisheye.undistortImage(frame, K, D, Knew=new_K)

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Reduce camera noise
            blurred = cv2.GaussianBlur(gray, (7, 7), 0)

            # Compare against the captured background
            diff = cv2.absdiff(bg, blurred)

            # Ignore small differences
            _, mask = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)

            # Remove small white noise
            kernel = np.ones((3, 3), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            #mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

            # Fill small gaps in detected regions
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

            # Invert mask colours (objects in black background in white)
            # mask = cv2.bitwise_not(mask)

            cv2.imshow(window_name, mask)

            # Stop if 'q' is pressed
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

            # Stop if the window is closed using the X button
            if cv2.getWindowProperty(
                    window_name, cv2.WND_PROP_VISIBLE
            ) < 1:
                break

    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("Streaming stopped.")


def capture_streaming_2() -> None:
    cap = cv2.VideoCapture(1)
    if not cap.isOpened():
        print("Error: Could not open video stream.")
        return

    print("Streaming started. Press 'q' or close the window to exit.")

    window_name = "Live Video Stream"

    try:
        while True:
            ret, frame = cap.read()

            if not ret:
                print("Error: Can't receive frame. Exiting...")
                break
            # Convert live frame to grayscale
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            blurred = cv2.GaussianBlur(gray, (7, 7), 0)
            cv2.imshow(window_name, gray)

            # Stop if 'q' is pressed
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

            # Stop if the window is closed using the X button
            if cv2.getWindowProperty(
                    window_name, cv2.WND_PROP_VISIBLE
            ) < 1:
                break

    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("Streaming stopped.")


def capture_bg() -> None:
    """Captures the background image that will be used"""
    cam = cv2.VideoCapture(1)
    success, frame = cam.read()

    #new_K = cv2.fisheye.estimateNewCameraMatrixForUndistortRectify(K, D, (w, h), np.eye(3), balance=0.0)

    #undistorted = cv2.fisheye.undistortImage(frame, K, D, Knew=new_K)

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 0)

    if success:
        cv2.imwrite("snapshot.jpg", blurred)
        print("Image captured successfully as 'snapshot.jpg'")

    # Free up the camera resource
    cam.release()


def list_cameras(max_cameras=10) -> []:
    available_cameras = []

    for index in range(max_cameras):
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)  # Windows
        if cap.isOpened():
            ret, _ = cap.read()

            if ret:
                available_cameras.append(index)
                print(f"Camera found at index {index}")

            cap.release()

    return available_cameras

if __name__ == "__main__":
    capture_bg()
    # list_cameras()
    capture_streaming()
    #capture_streaming_2()
