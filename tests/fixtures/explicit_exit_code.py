"""
Script calling sys.exit with an explicit non-zero exit code (42).
PyThaiTrace runner must preserve this exit code without rendering an error card.
"""
import sys

def main() -> None:
    print("Exiting with explicit code 42")
    sys.exit(42)

if __name__ == "__main__":
    main()
