import unittest

from jsonschema import Draft202012Validator

from _support import ROOT
from common import load_json


class SchemaValidationTests(unittest.TestCase):
    def test_all_schemas_are_valid(self):
        for path in (ROOT / "schemas").glob("*.schema.json"):
            Draft202012Validator.check_schema(load_json(path))


if __name__ == "__main__":
    unittest.main()
