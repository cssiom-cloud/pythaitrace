# Broken script: Missing colon on if statement
# This causes a compile-time SyntaxError before any runtime code is executed.

def broken_function():
    if True
        print("Missing colon above!")

if __name__ == "__main__":
    broken_function()
