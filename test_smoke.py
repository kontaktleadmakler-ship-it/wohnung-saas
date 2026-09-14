"""Fast, deterministic smoke test entry point.
Run with: python -m unittest discover -s tests -v
"""
import unittest
from tests.test_parsing import ParserTests
if __name__ == "__main__":
    unittest.main()
