"""Source supplement integrity; no Unreal or shared runtime state is used."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from tools import package_source_review as pack


class SourceReviewPackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / 'source'
        for name in pack.REQUIRED:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{}' if path.suffix in ('.json', '.uproject') else '# fixture\n', encoding='utf-8')

    def put(self, name, data='private fixture'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding='utf-8')

    def test_roundtrip_preserves_unicode_sources_and_required_controls(self):
        self.put('docs/проверка.md', 'Проверено')
        report = pack.create_bundle(self.root, self.base / 'пакет с пробелами')
        self.assertTrue(report['source_inputs_unchanged'])
        self.assertEqual(pack.verify_source_zip(report['archive'])['zip_sha256'], report['zip_sha256'])
        with zipfile.ZipFile(report['archive']) as archive:
            self.assertEqual(archive.read('docs/проверка.md').decode('utf-8'), 'Проверено')
            self.assertIn('controller/baselines.py', archive.namelist())

    def test_excludes_secrets_caches_and_binary_asset_inputs(self):
        for name in ('controller/.env', 'controller/secrets.env', 'controller/credentials.json',
                     'controller/__pycache__/bad.py', 'docs/assets/source.json',
                     'blender/model.blend', 'unreal/MetaRescue/Content/Scenario/bad.uasset'):
            self.put(name)
        selected = pack.source_files(self.root)
        self.assertEqual(set(selected), set(pack.REQUIRED))

    def test_missing_required_code_fails_before_output_creation(self):
        (self.root / 'controller/baselines.py').unlink()
        output = self.base / 'out'
        with self.assertRaisesRegex(ValueError, 'Required source'):
            pack.create_bundle(self.root, output)
        self.assertFalse(output.exists())

    def test_only_empty_upstream_api_template_may_be_included(self):
        self.put(pack.EMPTY_KEY_TEMPLATE, 'API=\n')
        self.assertIn(pack.EMPTY_KEY_TEMPLATE, pack.source_files(self.root))
        self.put(pack.EMPTY_KEY_TEMPLATE, 'API=nonempty-test-value\n')
        with self.assertRaisesRegex(ValueError, 'template is not empty'):
            pack.create_bundle(self.root, self.base / 'out')
        self.assertFalse((self.base / 'out').exists())

    def test_android_service_settings_are_removed_only_from_the_copy(self):
        name = 'unreal/MetaRescue/Config/DefaultEngine.ini'
        original = '[Before]\nKeep=1\n[/Script/AndroidFileServerEditor.Settings]\nSecurityToken=dummy-test-token\n[After]\nKeep=2\n'
        self.put(name, original)
        report = pack.create_bundle(self.root, self.base / 'out')
        with zipfile.ZipFile(report['archive']) as archive:
            copied = archive.read(name).decode('utf-8')
            self.assertNotIn('SecurityToken', copied)
            self.assertNotIn('dummy-test-token', copied)
            self.assertIn('[After]', copied)
        self.assertEqual((self.root / name).read_text(encoding='utf-8'), original)

    def test_refuses_existing_output_and_output_inside_workspace(self):
        output = self.base / 'out'
        output.mkdir()
        with self.assertRaises(FileExistsError):
            pack.create_bundle(self.root, output)
        with self.assertRaisesRegex(ValueError, 'outside'):
            pack.create_bundle(self.root, self.root / 'out')

    def test_source_edit_during_copy_leaves_no_accepted_zip(self):
        original = zipfile.ZipFile.writestr
        changed = False
        def mutate(archive, name, data, *args, **kwargs):
            nonlocal changed
            if not changed:
                (self.root / 'controller/baselines.py').write_text('changed', encoding='utf-8')
                changed = True
            return original(archive, name, data, *args, **kwargs)
        with patch.object(zipfile.ZipFile, 'writestr', mutate):
            with self.assertRaisesRegex(ValueError, 'Source'):
                pack.create_bundle(self.root, self.base / 'out')
        self.assertFalse((self.base / 'out/MetaRescue-source-review.zip').exists())

    def test_duplicate_and_unlisted_members_are_rejected(self):
        report = pack.create_bundle(self.root, self.base / 'out')
        with zipfile.ZipFile(report['archive'], 'a') as archive:
            archive.writestr('extra.txt', 'unexpected')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            pack.verify_source_zip(report['archive'])
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(report['archive'], 'a') as archive:
                archive.writestr('extra.txt', 'second')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            pack.verify_source_zip(report['archive'])

    def test_modified_member_with_valid_crc_is_rejected_by_sha(self):
        report = pack.create_bundle(self.root, self.base / 'out')
        bad = self.base / 'bad.zip'
        with zipfile.ZipFile(report['archive']) as source, zipfile.ZipFile(bad, 'w') as target:
            for name in source.namelist():
                target.writestr(name, b'changed' if name == 'controller/baselines.py' else source.read(name))
        with self.assertRaisesRegex(ValueError, 'checksum/size'):
            pack.verify_source_zip(bad)

    def test_path_traversal_member_is_rejected(self):
        report = pack.create_bundle(self.root, self.base / 'out')
        with zipfile.ZipFile(report['archive'], 'a') as archive:
            archive.writestr('../escape.txt', 'unexpected')
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            pack.verify_source_zip(report['archive'])
