"""
Fixture for TypeError: unsupported operand types.
"""

def calculate():
    user_age = "25"
    bonus_years = 5
    # TypeError: can only concatenate str (not "int") to str or unsupported operand type(s) for +: 'str' and 'int'
    total = user_age + bonus_years
    return total

if __name__ == "__main__":
    calculate()
