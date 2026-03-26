"""Simple calculator utilities."""


def add(a, b):
    return a + b


def subtract(a, b):
    return a - b


def multiply(a, b):
    return a * b


def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


def factorial(n):
    if not isinstance(n, int) or n < 0:
        raise ValueError("factorial requires a non-negative integer")
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result
