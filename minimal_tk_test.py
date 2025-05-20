import tkinter as tk
import threading
import time

def some_blocking_function():
    print("Minimal: Starting blocking function")
    time.sleep(5)  # Simulate a long-running task
    print("Minimal: Blocking function finished")

def call_after():
    print("Minimal: call_after running")

def main():
    root = tk.Tk()
    root.title("Minimal Tkinter Test")

    tk.Label(root, text="Testing Tkinter").pack(pady=20)

    # Try 1: Blocking call in main thread
    # some_blocking_function()  # Uncomment this to see the UI freeze

    # Try 2:  Blocking call in a thread (the original approach)
    threading.Thread(target=some_blocking_function, daemon=True).start()

    # Schedule a function to run later (should still work if Tkinter is responsive)
    root.after(1000, call_after)

    root.mainloop()

if __name__ == "__main__":
    main()