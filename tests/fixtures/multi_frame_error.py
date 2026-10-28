"""
Script triggering an exception through deeply nested function frames.
Tests that PyThaiTrace extracts the primary culprit frame correctly.
"""

def level_one(x: int):
    return level_two(x * 2)

def level_two(y: int):
    return level_three(y - 10)

def level_three(z: int):
    # Triggers ValueError
    return int("invalid_base_ten_" + str(z))

if __name__ == "__main__":
    level_one(5)
