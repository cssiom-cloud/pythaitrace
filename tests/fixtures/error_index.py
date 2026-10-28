"""
Fixture for IndexError: list index out of range.
"""

def get_item():
    fruits = ["apple", "banana", "mango"]
    # fruits has length 3 (indices 0, 1, 2)
    selected = fruits[99]
    return selected

if __name__ == "__main__":
    get_item()
