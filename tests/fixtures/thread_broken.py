"""
Script with worker thread raising an unhandled exception.
PyThaiTrace must intercept this via threading.excepthook.
"""
import threading
import time

def worker():
    time.sleep(0.05)
    raise RuntimeError("Worker thread encountered a catastrophic failure in background processing")

def main():
    t = threading.Thread(target=worker, name="WorkerThread-1")
    t.start()
    t.join()

if __name__ == "__main__":
    main()
