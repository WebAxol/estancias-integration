"""Exit with an error when a pytest JUnit report contains skipped tests or no tests."""
import sys
import xml.etree.ElementTree as ET

root = ET.parse(sys.argv[1]).getroot()
suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
tests = sum(int(s.get("tests", 0)) for s in suites)
skipped = sum(int(s.get("skipped", 0)) for s in suites)
print(f"tests={tests} skipped={skipped}")
if tests == 0 or skipped:
    sys.exit("Expected a non-empty run with no skipped tests")
