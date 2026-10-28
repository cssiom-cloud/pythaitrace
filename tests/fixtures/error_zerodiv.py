"""
Fixture for ZeroDivisionError: division or modulo by zero.
"""

def compute_ratio():
    numerator = 100
    denominator = 0
    result = numerator / denominator
    return result

if __name__ == "__main__":
    compute_ratio()
