"""
Clean script accepting and asserting specific command-line arguments.
"""
import sys

def main() -> None:
    args = sys.argv[1:]
    print(f"RECEIVED_ARGS: {args}")
    # Verify we can inspect flags
    if "--expected-flag" in args:
        print("FLAG_CONFIRMED: --expected-flag present")
    sys.exit(0)

if __name__ == "__main__":
    main()
