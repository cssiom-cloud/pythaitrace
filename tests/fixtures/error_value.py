"""
Fixture for ValueError: invalid literal in conversion function.
"""

def parse_integer():
    text_input = "not_a_valid_integer_123"
    # int() cannot convert non-numeric string
    parsed = int(text_input)
    return parsed

if __name__ == "__main__":
    parse_integer()
