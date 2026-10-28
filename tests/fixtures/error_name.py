"""
Fixture for NameError: references undefined variable.
"""

def main():
    user_name = "Somchai"
    # undefined_variable is not declared anywhere
    print(undefined_variable_counter)

if __name__ == "__main__":
    main()
