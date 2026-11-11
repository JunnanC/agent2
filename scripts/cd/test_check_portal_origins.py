import json
import tempfile
import unittest
from pathlib import Path

from importlib.machinery import SourceFileLoader


module = SourceFileLoader(
    "check_portal_origins", str(Path(__file__).with_name("check-portal-origins.py"))
).load_module()


class PortalOriginTests(unittest.TestCase):
    def test_ports_do_not_isolate_cookie_hosts(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory, ".env")
            compose = Path(directory, "resolved.json")
            env.write_text("STUDENT_HOST=portal.example:8081\nTEACHER_HOST=portal.example:8082\nADMIN_HOST=portal.example:8083\n")
            compose.write_text(json.dumps({"services": {"django": {"environment": {
                "DJANGO_TRUSTED_ORIGINS": ""
            }}}}))
            with self.assertRaisesRegex(SystemExit, "without schemes, paths or ports"):
                module.main(str(env), str(compose))

    def test_shared_cookie_host_is_rejected_even_with_different_case(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory, ".env")
            compose = Path(directory, "resolved.json")
            env.write_text("STUDENT_HOST=portal.example\nTEACHER_HOST=PORTAL.EXAMPLE.\nADMIN_HOST=a.example\n")
            compose.write_text(json.dumps({"services": {"django": {"environment": {
                "DJANGO_TRUSTED_ORIGINS": "https://portal.example,https://PORTAL.EXAMPLE.,https://a.example"
            }}}}))
            with self.assertRaisesRegex(SystemExit, "distinct hostnames"):
                module.main(str(env), str(compose))

    def test_ip_address_is_not_a_portal_hostname(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory, ".env")
            compose = Path(directory, "resolved.json")
            env.write_text("STUDENT_HOST=121.43.117.116\nTEACHER_HOST=t.example\nADMIN_HOST=a.example\n")
            compose.write_text(json.dumps({"services": {"django": {"environment": {
                "DJANGO_TRUSTED_ORIGINS": "https://121.43.117.116,https://t.example,https://a.example"
            }}}}))
            with self.assertRaisesRegex(SystemExit, "DNS hostnames"):
                module.main(str(env), str(compose))

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
