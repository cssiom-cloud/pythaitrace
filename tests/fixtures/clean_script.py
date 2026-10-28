"""
Clean script fixture for PyThaiTrace.
Prints to stdout and stderr, accepts optional arguments, and exits with code 0.
"""
import sys

def main() -> None:
    print("HELLO_STDOUT: PyThaiTrace clean execution")
    print("HELLO_STDERR: Status normal", file=sys.stderr)
    if len(sys.argv) > 1:
        print(f"ARGV: {sys.argv[1:]}")
    sys.exit(0)

if __name__ == "__main__":
    main()
