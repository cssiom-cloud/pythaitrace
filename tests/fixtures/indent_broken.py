# Broken script: Inconsistent unindent
# This causes a compile-time IndentationError before execution.

def check_indentation():
    x = 10
    if x > 5:
        print("x is greater than 5")
      print("Bad indentation level here")

if __name__ == "__main__":
    check_indentation()
