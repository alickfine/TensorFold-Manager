import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "manager"))

from tfmanager.state import APIError


class CredentialsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / "keychain-state.json"
        self.helper = self.root / "credential-helper"
        self.helper.write_text(
            "#!" + sys.executable + "\n"
            "import json, pathlib, sys\n"
            f"state_path=pathlib.Path({str(self.state)!r})\n"
            "request=json.loads(sys.stdin.read())\n"
            "state=json.loads(state_path.read_text()) if state_path.exists() else {}\n"
            "provider=request['provider']; operation=request['operation']\n"
            "if operation == 'set': state[provider]=request['token']; state_path.write_text(json.dumps(state)); response={'configured':True}\n"
            "elif operation == 'get': response=({'configured':True,'token':state[provider]} if provider in state else {'configured':False})\n"
            "elif operation == 'delete': state.pop(provider,None); state_path.write_text(json.dumps(state)); response={'configured':False}\n"
            "else: response={'configured':provider in state}\n"
            "print(json.dumps(response))\n"
        )
        self.helper.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

    def test_round_trip_only_reveals_secret_from_explicit_get(self):
        from tfmanager.credentials import Credentials

        credentials = Credentials(self.helper)
        self.assertEqual(credentials.status("hf-upload"), {"provider": "hf-upload", "configured": False})
        self.assertEqual(
            credentials.set("hf-upload", "private-example-token"),
            {"provider": "hf-upload", "configured": True},
        )
        self.assertEqual(credentials.get("hf-upload"), "private-example-token")
        self.assertEqual(
            credentials.delete("hf-upload"),
            {"provider": "hf-upload", "configured": False},
        )
        with self.assertRaisesRegex(APIError, "not configured"):
            credentials.get("hf-upload")

    def test_provider_helper_and_payload_bounds_are_enforced(self):
        from tfmanager.credentials import Credentials

        credentials = Credentials(self.helper)
        for provider in ("hf", "../../login", "HF-UPLOAD"):
            with self.assertRaises(APIError):
                credentials.status(provider)
        with self.assertRaises(APIError):
            Credentials(Path("relative-helper")).status("hf-upload")
        with self.assertRaises(APIError):
            credentials.set("hf-upload", "x" * 8193)
        with self.assertRaises(APIError):
            credentials.set("hf-upload", "line1\nline2")

    def test_helper_failure_cannot_echo_secret_into_error(self):
        from tfmanager.credentials import Credentials

        leaking = self.root / "leaking-helper"
        secret = "private-credential-without-provider-prefix"
        leaking.write_text(
            "#!" + sys.executable + "\n"
            "import json,sys\n"
            "request=json.loads(sys.stdin.read())\n"
            "sys.stderr.write(request.get('token',''))\n"
            "raise SystemExit(23)\n"
        )
        leaking.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        with self.assertRaises(APIError) as caught:
            Credentials(leaking).set("hf-upload", secret)
        self.assertNotIn(secret, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
