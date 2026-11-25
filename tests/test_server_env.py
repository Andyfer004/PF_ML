import importlib.util
import stat
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('server_env', Path(__file__).resolve().parents[1] / 'scripts/server_env.py')
env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(env)


class ServerEnvTests(unittest.TestCase):
    def test_literal_values_and_preserved_configuration(self):
        value = 'synthetic$VALUE # /+=123'
        result = env.update_env('# configuration\nAPI_BIND_HOST=0.0.0.0\nKEY=old\nKEY=duplicate\nAWS_SESSION_TOKEN=old\n', {'KEY': value, 'AWS_SESSION_TOKEN': None})
        self.assertEqual(env.parse_env(result), {'API_BIND_HOST': '0.0.0.0', 'KEY': value})
        self.assertEqual(result.count('KEY='), 1)
        self.assertIn("KEY='" + value + "'", result)

    def test_invalid_values_do_not_appear_in_errors(self):
        for value in ['private\nvalue', 'private\rvalue', "private'value", 'private\x00value']:
            with self.assertRaises(ValueError) as caught:
                env.update_env('', {'KEY': value})
            self.assertNotIn('private', str(caught.exception))

    def test_atomic_private_file_and_symlink_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            env.write_env_atomic(path, 'KEY=synthetic\n')
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(list(Path(directory).iterdir()), [path])
            link = Path(directory) / 'link'
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                env.write_env_atomic(link, 'CHANGED=yes\n')
            self.assertEqual(path.read_text(), 'KEY=synthetic\n')

    def test_malformed_env_is_rejected_without_values(self):
        with self.assertRaises(ValueError) as caught:
            env.parse_env('KEY="private')
        self.assertNotIn('private', str(caught.exception))
