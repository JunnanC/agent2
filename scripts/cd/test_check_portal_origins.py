import json
import tempfile
import unittest
from pathlib import Path

from importlib.machinery import SourceFileLoader


module = SourceFileLoader(
    "check_portal_origins", str(Path(__file__).with_name("check-portal-origins.py"))
).load_module()


class PortalOriginTests(unittest.TestCase):
    def test_missing_https_origin_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory, ".env")
            compose = Path(directory, "resolved.json")
            env.write_text("STUDENT_HOST=s.example\nTEACHER_HOST=t.example\nADMIN_HOST=a.example\n")
            compose.write_text(json.dumps({"services": {"django": {"environment": {
                "DJANGO_TRUSTED_ORIGINS": "https://s.example,https://t.example"
            }}}}))
            with self.assertRaisesRegex(SystemExit, "https://a.example"):
                module.main(str(env), str(compose))
            data = json.loads(compose.read_text())
            data["services"]["django"]["environment"]["DJANGO_TRUSTED_ORIGINS"] += ",https://a.example"
            compose.write_text(json.dumps(data))
            module.main(str(env), str(compose))
