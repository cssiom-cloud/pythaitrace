"""
Fixture for AttributeError: attribute does not exist on target object.
"""

def process_text():
    raw_message = "hello world"
    # str object has no attribute 'calculate_sum'
    result = raw_message.calculate_sum()
    return result

if __name__ == "__main__":
    process_text()
