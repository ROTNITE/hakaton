"""Launch configuration: Secret.env in the same directory as main.py."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
SPEC=importlib.util.spec_from_file_location('metarescue_main_for_tests',ROOT/'main.py')
ENTRY=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ENTRY)

class TestSecretEnv(unittest.TestCase):
    def test_secret_env_api_equals_is_loaded_without_printing(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            (folder/'Secret.env').write_text('\ufeff# комментарий\nAPI = "test-key-placeholder"\n',encoding='utf-8')
            with patch.object(ENTRY,'ROOT',folder), patch.dict(os.environ,{},clear=True):
                ENTRY.load_local_settings()
                self.assertEqual(os.environ.get('DEEPSEEK_API_KEY'),'test-key-placeholder')

    def test_missing_file_keeps_process_running(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(ENTRY,'ROOT',Path(d)), patch.dict(os.environ,{},clear=True):
                ENTRY.load_local_settings()
                self.assertNotIn('DEEPSEEK_API_KEY',os.environ)

    def test_is_not_read_from_current_working_directory(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as other:
            (Path(other)/'Secret.env').write_text('API=not-for-this-project\n',encoding='utf-8')
            with patch.object(ENTRY,'ROOT',Path(d)), patch.dict(os.environ,{},clear=True),patch('os.getcwd',return_value=other):
                ENTRY.load_local_settings()
                self.assertNotIn('DEEPSEEK_API_KEY',os.environ)

if __name__=='__main__':unittest.main()
